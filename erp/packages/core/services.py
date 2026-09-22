from __future__ import annotations

import hmac
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Select, case, delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from erp.packages.core.config import Settings, get_settings
from erp.packages.core.db.models import (
    AuditLog,
    AuthActionToken,
    AuthRefreshToken,
    AuthSession,
    Company,
    LoginThrottle,
    Permission,
    Role,
    RolePermission,
    Setting,
    User,
    UserRole,
    Vendor,
    VendorUser,
    new_uuid,
)
from erp.packages.core.modules.manifest import load_module_manifests
from erp.packages.core.schemas import FirstUseSetupRequest
from erp.packages.core.security import (
    generate_session_token,
    hash_password,
    hash_session_token,
    verify_password,
)


class ServiceError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass(frozen=True)
class AuthContext:
    user: User
    company: Company | None
    session: AuthSession
    permissions: list[str]


@dataclass(frozen=True)
class IssuedSession:
    token: str
    session: AuthSession
    user: User
    company: Company | None
    permissions: list[str]
    refresh_token: str | None = None
    refresh_expires_at: datetime | None = None
    remember_me: bool = False


ADMINISTRATOR_ROLE_NAME = "Administrator"
VENDOR_ROLE_NAME = "Vendor"
VENDOR_ROLE_DESCRIPTION = "Default vendor role with canonical portal permissions."
MANAGER_ROLE_NAME = "Manager"
MANAGER_ROLE_DESCRIPTION = "Default manager role for operations."
VENDOR_SELF_SERVICE_PERMISSIONS = frozenset(
    {
        "vendor.profile.view",
        "vendor.products.view",
        "vendor.products.manage",
        "vendor.orders.view",
        "vendor.orders.manage",
        "vendor.settlements.view",
        "vendor.ledger.view",
        "vendor.stock.view",
        "vendor.stock.manage",
        "vendor.reports.view",
        "vendor.shop.purchases.manage",
        "vendor.shop.accounting.view",
    }
)
MANAGER_CORE_PERMISSIONS = frozenset(
    {
        "catalog.view",
        "catalog.manage",
        "customers.view",
        "customers.manage",
        "inventory.view",
        "inventory.manage",
        "inventory.transfer",
        "orders.view",
        "orders.manage",
        "orders.change_status",
        "delivery.manage",
        "reports.view",
        "reports.export",
    }
)
ACCOUNT_STATUSES = {"active", "pending", "paused", "stopped"}
COMPANY_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")


def utcnow() -> datetime:
    return datetime.now(UTC)


def to_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def normalize_company_slug(value: str) -> str:
    slug = COMPANY_SLUG_PATTERN.sub("-", value.strip().lower()).strip("-")
    return slug or "company"


def unique_company_slug(
    db: Session,
    value: str,
    *,
    exclude_company_id: str | None = None,
) -> str:
    base_slug = normalize_company_slug(value)
    slug = base_slug
    suffix = 2
    while True:
        query = select(Company).where(Company.slug == slug)
        if exclude_company_id:
            query = query.where(Company.id != exclude_company_id)
        if db.scalar(query) is None:
            return slug
        slug = f"{base_slug}-{suffix}"
        suffix += 1


def declared_permissions() -> list[str]:
    keys: set[str] = set()
    settings = get_settings()
    for manifest in load_module_manifests():
        if manifest.id == "whatsapp" and not settings.effective_whatsapp_enabled:
            continue
        keys.update(manifest.permissions)
    return sorted(keys)


def ensure_declared_permission_rows(db: Session) -> dict[str, Permission]:
    existing = {row.key: row for row in db.scalars(select(Permission)).all()}
    added_permissions = False
    for key in declared_permissions():
        if key not in existing:
            permission = Permission(key=key, description=f"Permission: {key}")
            db.add(permission)
            existing[key] = permission
            added_permissions = True
    if added_permissions:
        db.flush()
    return existing


def seed_default_roles(db: Session, company_id: str | None) -> None:
    permissions = ensure_declared_permission_rows(db)

    defaults = {
        ADMINISTRATOR_ROLE_NAME: {
            "description": "Full system administrator.",
            "perms": set(permissions.keys()),
            "overwrite": True,
        },
        VENDOR_ROLE_NAME: {
            "description": VENDOR_ROLE_DESCRIPTION,
            "perms": VENDOR_SELF_SERVICE_PERMISSIONS,
            "overwrite": False,
        },
        "Rider": {
            "description": "Default rider role for delivery assignments.",
            "perms": {
                "delivery.view_assigned",
                "delivery.update_assigned",
                "rider.finance.view",
                "rider.finance.submit",
            },
            "overwrite": False,
        },
        MANAGER_ROLE_NAME: {
            "description": MANAGER_ROLE_DESCRIPTION,
            "perms": MANAGER_CORE_PERMISSIONS,
            "overwrite": False,
        },
    }

    added_role_permissions = False

    for role_name, config in defaults.items():
        role = db.scalar(select(Role).where(Role.company_id == company_id, Role.name == role_name))

        if not role:
            role = Role(company_id=company_id, name=role_name, description=config["description"])
            db.add(role)
            db.flush()

            for perm_key in config["perms"]:
                if perm_key in permissions:
                    db.add(RolePermission(role_id=role.id, permission_id=permissions[perm_key].id))
                    added_role_permissions = True
        else:
            # Keep explicitly customized vendor roles intact. The canonical
            # default role is synchronized so new shop permissions reach
            # existing vendor accounts after an upgrade.
            if config["overwrite"] or (
                role_name == VENDOR_ROLE_NAME
                and role.description == VENDOR_ROLE_DESCRIPTION
            ):
                existing_permission_ids = set(
                    db.scalars(
                        select(RolePermission.permission_id).where(
                            RolePermission.role_id == role.id
                        )
                    ).all()
                )
                for perm_key in config["perms"]:
                    if perm_key in permissions:
                        perm_id = permissions[perm_key].id
                        if perm_id not in existing_permission_ids:
                            db.add(RolePermission(role_id=role.id, permission_id=perm_id))
                            added_role_permissions = True

    if added_role_permissions:
        db.flush()


def is_configured(db: Session) -> bool:
    return bool(db.scalar(select(func.count(User.id))))


def record_audit(
    db: Session,
    *,
    action: str,
    company_id: str | None = None,
    user_id: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    entry = AuditLog(
        company_id=company_id,
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        metadata_json=metadata or {},
    )
    db.add(entry)
    return entry


def user_permissions_query(user_id: str) -> Select[tuple[str]]:
    return (
        select(Permission.key)
        .distinct()
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(UserRole, UserRole.role_id == RolePermission.role_id)
        .join(Role, Role.id == UserRole.role_id)
        .join(User, User.id == UserRole.user_id)
        .where(
            UserRole.user_id == user_id,
            or_(
                Role.company_id == User.company_id,
                Role.company_id.is_(None),
            ),
            ~(
                (Role.name == VENDOR_ROLE_NAME)
                & Permission.key.not_in(VENDOR_SELF_SERVICE_PERMISSIONS)
            ),
        )
        .order_by(Permission.key)
    )


def get_user_permissions(db: Session, user_id: str) -> list[str]:
    return list(db.scalars(user_permissions_query(user_id)).all())


def company_for_user(db: Session, user: User) -> Company | None:
    if not user.company_id:
        return None
    return db.get(Company, user.company_id)


def user_role_names(db: Session, user_id: str) -> set[str]:
    return set(
        db.scalars(
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .join(User, User.id == UserRole.user_id)
            .where(
                UserRole.user_id == user_id,
                or_(Role.company_id == User.company_id, Role.company_id.is_(None)),
            )
        ).all()
    )


def canonical_vendor_status(value: str) -> str:
    return {
        "approved": "active",
        "suspended": "paused",
        "rejected": "stopped",
    }.get(value.strip().lower(), value.strip().lower())


def ensure_login_allowed(db: Session, user: User, *, status_code: int = 403) -> None:
    """Enforce account, tenant, and vendor-role eligibility in one place."""

    account_status = (user.account_status or "stopped").strip().lower()
    if not user.is_active or account_status != "active":
        raise ServiceError(status_code, f"Account is {account_status}.")

    company = company_for_user(db, user)
    if user.company_id and (company is None or company.status.strip().lower() != "active"):
        raise ServiceError(status_code, "Company account is not active.")

    roles = user_role_names(db, user.id)
    if ADMINISTRATOR_ROLE_NAME in roles or VENDOR_ROLE_NAME not in roles:
        return

    vendor_links = list(
        db.scalars(
            select(VendorUser).where(
                VendorUser.user_id == user.id,
                VendorUser.company_id == user.company_id,
            )
        ).all()
    )
    primary_links = [link for link in vendor_links if link.is_primary]
    if len(primary_links) == 1:
        link = primary_links[0]
    elif not primary_links and len(vendor_links) == 1:
        # Compatibility for a legacy single relationship created before
        # ``is_primary`` was introduced.
        link = vendor_links[0]
    elif len(primary_links) > 1 or len(vendor_links) > 1:
        raise ServiceError(409, "Vendor account relationship is ambiguous.")
    else:
        raise ServiceError(status_code, "Vendor account relationship is unavailable.")

    vendor = db.scalar(
        select(Vendor).where(
            Vendor.id == link.vendor_id,
            Vendor.company_id == user.company_id,
        )
    )
    vendor_status = canonical_vendor_status(vendor.status) if vendor else "stopped"
    if vendor is None or vendor_status != "active":
        raise ServiceError(status_code, f"Vendor account is {vendor_status}.")


def login_scope_key(
    *, username: str, company_id: str | None, workspace_slug: str | None, ip_address: str | None
) -> str:
    raw = "|".join(
        [
            username.strip().lower(),
            company_id or "",
            workspace_slug or "",
            ip_address or "unknown",
        ]
    )
    # Store only a keyed digest so usernames and addresses are not duplicated in
    # the throttling table.
    return hash_session_token(raw)


def auth_throttle_scope_keys(
    *,
    action: str,
    account_identifier: str,
    workspace: str | None = None,
    ip_address: str | None = None,
) -> tuple[str, ...]:
    """Build independent, non-identifying account/workspace and IP scopes."""

    normalized_workspace = normalize_company_slug(workspace) if workspace else "unscoped"
    account_raw = "|".join(
        [
            action.strip().lower(),
            "account",
            account_identifier.strip().lower(),
            normalized_workspace,
        ]
    )
    keys = [hash_session_token(account_raw)]
    if ip_address:
        ip_raw = "|".join([action.strip().lower(), "ip", ip_address.strip().lower()])
        keys.append(hash_session_token(ip_raw))
    return tuple(keys)


def login_throttle_scope_key(
    *,
    account_identifier: str,
    workspace: str | None = None,
    login_device_id: str | None = None,
    ip_address: str | None = None,
) -> str:
    """Build one login throttle scope for an account and device."""

    normalized_workspace = normalize_company_slug(workspace) if workspace else "unscoped"
    device_scope = (login_device_id or "").strip().lower()
    if not device_scope:
        device_scope = f"ip:{(ip_address or 'unknown').strip().lower()}"
    raw = "|".join(
        [
            "login",
            "account",
            account_identifier.strip().lower(),
            normalized_workspace,
            device_scope,
        ]
    )
    return hash_session_token(raw)


def check_auth_throttle(db: Session, scope_keys: tuple[str, ...]) -> None:
    if not scope_keys:
        return
    now = utcnow()
    blocked = db.scalar(
        select(LoginThrottle.id).where(
            LoginThrottle.scope_key.in_(scope_keys),
            LoginThrottle.blocked_until.is_not(None),
            LoginThrottle.blocked_until > now,
        )
    )
    if blocked:
        raise ServiceError(429, "Too many attempts. Try again later.")


def record_auth_throttle_attempt(db: Session, scope_keys: tuple[str, ...]) -> None:
    if not scope_keys:
        return
    settings = get_settings()
    now = utcnow()
    window = timedelta(minutes=settings.login_attempt_window_minutes)
    window_cutoff = now - window
    blocked_until = now + timedelta(minutes=settings.login_block_minutes)
    throttle_cutoff = now - timedelta(days=settings.auth_throttle_retention_days)
    db.execute(
        delete(LoginThrottle)
        .where(LoginThrottle.updated_at < throttle_cutoff)
        .execution_options(synchronize_session=False)
    )
    table = LoginThrottle.__table__
    dialect_name = db.get_bind().dialect.name
    insert_factory = postgresql_insert if dialect_name == "postgresql" else sqlite_insert

    for scope_key in scope_keys:
        statement = insert_factory(table).values(
            id=new_uuid(),
            scope_key=scope_key,
            failure_count=1,
            window_started_at=now,
            blocked_until=None,
            updated_at=now,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[table.c.scope_key],
            set_={
                "failure_count": case(
                    (table.c.window_started_at <= window_cutoff, 1),
                    else_=table.c.failure_count + 1,
                ),
                "window_started_at": case(
                    (table.c.window_started_at <= window_cutoff, now),
                    else_=table.c.window_started_at,
                ),
                "blocked_until": case(
                    (table.c.window_started_at <= window_cutoff, None),
                    (
                        table.c.failure_count + 1 >= settings.login_attempt_limit,
                        blocked_until,
                    ),
                    else_=table.c.blocked_until,
                ),
                "updated_at": now,
            },
        )
        db.execute(statement)


def clear_auth_throttle(db: Session, scope_keys: tuple[str, ...]) -> None:
    if scope_keys:
        db.execute(delete(LoginThrottle).where(LoginThrottle.scope_key.in_(scope_keys)))


def check_login_throttle(db: Session, scope_key: str) -> None:
    check_auth_throttle(db, (scope_key,))


def record_login_failure(db: Session, scope_key: str) -> None:
    record_auth_throttle_attempt(db, (scope_key,))


def clear_login_throttle(db: Session, scope_key: str) -> None:
    clear_auth_throttle(db, (scope_key,))


def prune_auth_sessions(db: Session, *, user_id: str | None = None) -> None:
    """Prune only records expired beyond the configured security retention."""

    del user_id  # Retention is chronological; active records are never selected.
    settings = get_settings()
    now = utcnow()
    auth_cutoff = now - timedelta(days=settings.auth_record_retention_days)
    throttle_cutoff = now - timedelta(days=settings.auth_throttle_retention_days)

    db.execute(
        delete(AuthRefreshToken)
        .where(AuthRefreshToken.expires_at < auth_cutoff)
        .execution_options(synchronize_session=False)
    )
    db.execute(
        delete(AuthActionToken)
        .where(AuthActionToken.expires_at < auth_cutoff)
        .execution_options(synchronize_session=False)
    )
    refresh_exists = (
        select(AuthRefreshToken.id).where(AuthRefreshToken.session_id == AuthSession.id).exists()
    )
    db.execute(
        delete(AuthSession)
        .where(
            AuthSession.expires_at < auth_cutoff,
            ~refresh_exists,
        )
        .execution_options(synchronize_session=False)
    )
    db.execute(
        delete(LoginThrottle)
        .where(LoginThrottle.updated_at < throttle_cutoff)
        .execution_options(synchronize_session=False)
    )


def issue_session(
    db: Session,
    user: User,
    *,
    user_agent: str | None = None,
    ip_address: str | None = None,
    remember_me: bool = False,
    family_id: str | None = None,
    refresh_capable: bool = False,
) -> IssuedSession:
    settings = get_settings()
    token = generate_session_token()
    expires_at = utcnow() + (
        timedelta(minutes=settings.access_token_ttl_minutes)
        if refresh_capable or remember_me
        else timedelta(hours=settings.session_ttl_hours)
    )
    prune_auth_sessions(db, user_id=user.id)
    session = AuthSession(
        user_id=user.id,
        token_hash=hash_session_token(token, settings),
        user_agent=user_agent,
        expires_at=expires_at,
    )
    db.add(session)
    db.flush()
    refresh_token = generate_session_token()
    refresh_expires_at = utcnow() + (
        timedelta(days=settings.remember_me_ttl_days)
        if remember_me
        else timedelta(hours=settings.refresh_token_ttl_hours)
    )
    db.add(
        AuthRefreshToken(
            user_id=user.id,
            session_id=session.id,
            family_id=family_id or new_uuid(),
            token_hash=hash_session_token(refresh_token, settings),
            remember_me=remember_me,
            user_agent=user_agent,
            ip_address=ip_address,
            expires_at=refresh_expires_at,
        )
    )
    db.flush()
    seed_default_roles(db, user.company_id)
    permissions = get_user_permissions(db, user.id)
    return IssuedSession(
        token=token,
        session=session,
        user=user,
        company=company_for_user(db, user),
        permissions=permissions,
        refresh_token=refresh_token,
        refresh_expires_at=refresh_expires_at,
        remember_me=remember_me,
    )


def setup_first_use(
    db: Session,
    payload: FirstUseSetupRequest,
    *,
    user_agent: str | None = None,
    bootstrap_token: str | None = None,
    settings: Settings | None = None,
) -> IssuedSession:
    active_settings = settings or get_settings()
    if active_settings.is_production and not hmac.compare_digest(
        bootstrap_token or "",
        active_settings.bootstrap_token,
    ):
        raise ServiceError(401, "First-use setup authorization failed.")

    dialect_name = db.get_bind().dialect.name
    if dialect_name == "postgresql":
        # Transaction-scoped lock serializes first-administrator creation across
        # processes without introducing another schema object.
        db.execute(text("SELECT pg_advisory_xact_lock(202607010015)"))
    elif dialect_name == "sqlite":
        # Acquire SQLite's single writer reservation before the configured check.
        db.execute(text("BEGIN IMMEDIATE"))

    if is_configured(db):
        raise ServiceError(409, "First-use setup has already been completed.")

    company_id = new_uuid()
    requested_slug = payload.workspace_slug or payload.company_name
    company = Company(
        id=company_id,
        name=payload.company_name,
        slug=unique_company_slug(db, requested_slug),
        status="active",
    )
    user = User(
        company_id=company_id,
        username=payload.username,
        email=payload.email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        is_active=True,
        account_status="active",
        password_changed_at=utcnow(),
    )
    admin_role = Role(
        company_id=company_id,
        name="Administrator",
        description="Full system administrator created during first-use setup.",
    )

    db.add_all([company, user, admin_role])
    db.flush()

    # Migrations may already have created the global permission catalogue.
    # Reuse those rows (and add only any newly declared permissions) instead
    # of inserting duplicate keys during first-use setup.
    permission_catalog = ensure_declared_permission_rows(db)
    permission_rows = [permission_catalog[key] for key in declared_permissions()]

    db.add(UserRole(user_id=user.id, role_id=admin_role.id))
    db.add_all(
        RolePermission(role_id=admin_role.id, permission_id=permission.id)
        for permission in permission_rows
    )
    record_audit(
        db,
        action="setup.first_use_completed",
        company_id=company.id,
        user_id=user.id,
        entity_type="company",
        entity_id=company.id,
        metadata={"company_name": company.name, "username": user.username},
    )
    issued = issue_session(db, user, user_agent=user_agent)
    record_audit(
        db,
        action="auth.session_created",
        company_id=company.id,
        user_id=user.id,
        entity_type="auth_session",
        entity_id=issued.session.id,
        metadata={"reason": "first_use_setup"},
    )
    return issued


def authenticate(
    db: Session,
    *,
    username: str,
    password: str,
    company_id: str | None = None,
    workspace_slug: str | None = None,
    user_agent: str | None = None,
    ip_address: str | None = None,
    login_device_id: str | None = None,
    remember_me: bool = False,
    refresh_capable: bool = False,
) -> IssuedSession:
    if not is_configured(db):
        record_audit(
            db,
            action="auth.login_failed",
            metadata={"username": username, "reason": "first_use_setup_required"},
        )
        raise ServiceError(409, "First-use setup is required before login.")

    workspace_scope = workspace_slug or company_id
    login_scope_key = login_throttle_scope_key(
        account_identifier=username,
        workspace=workspace_scope,
        login_device_id=login_device_id,
        ip_address=ip_address,
    )
    scope_keys = (login_scope_key,)
    check_auth_throttle(db, scope_keys)
    scoped_company_id = company_id
    if workspace_slug:
        company = db.scalar(
            select(Company).where(Company.slug == normalize_company_slug(workspace_slug))
        )
        if company is None:
            record_audit(
                db,
                action="auth.login_failed",
                metadata={"username": username, "workspace_slug": workspace_slug},
            )
            record_auth_throttle_attempt(db, scope_keys)
            raise ServiceError(401, "Invalid username or password.")
        if company_id and company.id != company_id:
            raise ServiceError(422, "Workspace slug does not match company ID.")
        scoped_company_id = company.id

    query = select(User).where(
        or_(User.username == username, User.email == username),
    )
    if scoped_company_id:
        query = query.where(User.company_id == scoped_company_id)
    users = list(db.scalars(query).all())
    if not scoped_company_id and len(users) > 1:
        record_audit(
            db,
            action="auth.login_failed",
            metadata={"username": username, "reason": "ambiguous_workspace"},
        )
        record_auth_throttle_attempt(db, scope_keys)
        raise ServiceError(409, "Workspace slug is required for this username.")
    user = users[0] if users else None
    if user is None or not verify_password(password, user.password_hash):
        record_audit(
            db,
            action="auth.login_failed",
            metadata={
                "username": username,
                "company_id": scoped_company_id,
                "workspace_slug": workspace_slug,
            },
        )
        record_auth_throttle_attempt(db, scope_keys)
        raise ServiceError(401, "Invalid username or password.")

    ensure_login_allowed(db, user)
    # A successful authentication clears only this account/device scope.
    clear_auth_throttle(db, scope_keys)
    user.last_login_at = utcnow()
    issued = issue_session(
        db,
        user,
        user_agent=user_agent,
        ip_address=ip_address,
        remember_me=remember_me,
        refresh_capable=refresh_capable,
    )
    record_audit(
        db,
        action="auth.login_succeeded",
        company_id=user.company_id,
        user_id=user.id,
        entity_type="auth_session",
        entity_id=issued.session.id,
        metadata={"username": user.username},
    )
    return issued


def context_from_token(db: Session, token: str) -> AuthContext:
    token_hash = hash_session_token(token)
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash))
    if session is None or session.revoked_at is not None:
        raise ServiceError(401, "Authentication session is invalid or expired.")
    session_expires_at = to_utc(session.expires_at)
    if session_expires_at is None or session_expires_at <= utcnow():
        raise ServiceError(401, "Authentication session is invalid or expired.")

    user = db.get(User, session.user_id)
    if user is None:
        raise ServiceError(401, "Authenticated user is not active.")
    ensure_login_allowed(db, user, status_code=401)

    # Authentication must be read-only in the usual case. This function runs
    # before every authenticated endpoint, including simple product/detail
    # reads. Updating ``last_seen_at`` here turns every click into a SQLite
    # writer. A WooCommerce run can legitimately hold a writer transaction
    # while it waits for WordPress, which then causes normal screens to block
    # behind it and appear offline. The permission helper only writes when an
    # upgrade genuinely introduced missing permissions, preserving the
    # existing automatic permission-backfill behavior without writing on each
    # request.
    seed_default_roles(db, user.company_id)
    return AuthContext(
        user=user,
        company=company_for_user(db, user),
        session=session,
        permissions=get_user_permissions(db, user.id),
    )


def revoke_user_sessions(
    db: Session,
    user_id: str,
    *,
    except_session_id: str | None = None,
) -> None:
    now = utcnow()
    session_stmt = (
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    refresh_stmt = (
        update(AuthRefreshToken)
        .where(AuthRefreshToken.user_id == user_id, AuthRefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    if except_session_id:
        session_stmt = session_stmt.where(AuthSession.id != except_session_id)
        refresh_stmt = refresh_stmt.where(AuthRefreshToken.session_id != except_session_id)
    db.execute(session_stmt)
    db.execute(refresh_stmt)


def revoke_refresh_family(db: Session, family_id: str) -> None:
    rows = list(
        db.scalars(select(AuthRefreshToken).where(AuthRefreshToken.family_id == family_id)).all()
    )
    now = utcnow()
    session_ids: list[str] = []
    for row in rows:
        row.revoked_at = row.revoked_at or now
        session_ids.append(row.session_id)
    if session_ids:
        db.execute(
            update(AuthSession)
            .where(AuthSession.id.in_(session_ids), AuthSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )


def rotate_refresh_token(
    db: Session,
    refresh_token: str,
    *,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> IssuedSession:
    token_hash = hash_session_token(refresh_token)
    now = utcnow()
    consume_result = db.execute(
        update(AuthRefreshToken)
        .where(
            AuthRefreshToken.token_hash == token_hash,
            AuthRefreshToken.used_at.is_(None),
            AuthRefreshToken.revoked_at.is_(None),
            AuthRefreshToken.expires_at > now,
        )
        .values(used_at=now)
        .execution_options(synchronize_session=False)
    )
    current = db.scalar(select(AuthRefreshToken).where(AuthRefreshToken.token_hash == token_hash))
    if consume_result.rowcount != 1:
        if current is None:
            raise ServiceError(401, "Refresh token is invalid or expired.")
        if to_utc(current.expires_at) <= now:
            current.revoked_at = current.revoked_at or now
            raise ServiceError(401, "Refresh token is invalid or expired.")
        revoke_refresh_family(db, current.family_id)
        record_audit(
            db,
            action="auth.refresh_reuse_detected",
            user_id=current.user_id,
            entity_type="auth_refresh_family",
            entity_id=current.family_id,
        )
        raise ServiceError(401, "Refresh token reuse was detected; the session was revoked.")

    if current is None:  # Defensive: the successful conditional update owns this row.
        raise ServiceError(401, "Refresh token is invalid or expired.")
    user = db.get(User, current.user_id)
    if user is None:
        revoke_refresh_family(db, current.family_id)
        raise ServiceError(401, "Refresh token is invalid or expired.")
    try:
        ensure_login_allowed(db, user, status_code=401)
    except ServiceError:
        revoke_refresh_family(db, current.family_id)
        raise

    old_session = db.get(AuthSession, current.session_id)
    if old_session is not None:
        old_session.revoked_at = now
    issued = issue_session(
        db,
        user,
        user_agent=user_agent or current.user_agent,
        ip_address=ip_address or current.ip_address,
        remember_me=current.remember_me,
        family_id=current.family_id,
        refresh_capable=True,
    )
    replacement = db.scalar(
        select(AuthRefreshToken).where(
            AuthRefreshToken.token_hash == hash_session_token(issued.refresh_token or "")
        )
    )
    current.replaced_by_id = replacement.id if replacement else None
    record_audit(
        db,
        action="auth.refresh_rotated",
        company_id=user.company_id,
        user_id=user.id,
        entity_type="auth_session",
        entity_id=issued.session.id,
    )
    return issued


def revoke_session(
    db: Session,
    context: AuthContext,
    *,
    refresh_token: str | None = None,
    all_sessions: bool = False,
) -> None:
    if all_sessions:
        revoke_user_sessions(db, context.user.id)
    else:
        context.session.revoked_at = utcnow()
        db.execute(
            update(AuthRefreshToken)
            .where(
                AuthRefreshToken.session_id == context.session.id,
                AuthRefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=utcnow())
        )
        if refresh_token:
            refresh_row = db.scalar(
                select(AuthRefreshToken).where(
                    AuthRefreshToken.token_hash == hash_session_token(refresh_token),
                    AuthRefreshToken.user_id == context.user.id,
                )
            )
            if refresh_row:
                revoke_refresh_family(db, refresh_row.family_id)
    record_audit(
        db,
        action="auth.logout",
        company_id=context.user.company_id,
        user_id=context.user.id,
        entity_type="auth_session",
        entity_id=context.session.id,
        metadata={"all_sessions": all_sessions},
    )


def revoke_refresh_token(
    db: Session,
    refresh_token: str,
    *,
    expected_user_id: str | None = None,
) -> AuthRefreshToken | None:
    """Revoke a refresh family by possession, without revealing token validity."""

    row = db.scalar(
        select(AuthRefreshToken).where(
            AuthRefreshToken.token_hash == hash_session_token(refresh_token)
        )
    )
    if row is None or (expected_user_id is not None and row.user_id != expected_user_id):
        return None
    revoke_refresh_family(db, row.family_id)
    return row


def create_action_token(
    db: Session,
    user: User,
    purpose: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> tuple[str, AuthActionToken]:
    if purpose not in {"activation", "password_reset"}:
        raise ServiceError(422, "Unsupported action-token purpose.")
    now = utcnow()
    prune_auth_sessions(db, user_id=user.id)
    db.execute(
        update(AuthActionToken)
        .where(
            AuthActionToken.user_id == user.id,
            AuthActionToken.purpose == purpose,
            AuthActionToken.consumed_at.is_(None),
        )
        .values(consumed_at=now)
        .execution_options(synchronize_session=False)
    )
    plain_token = generate_session_token()
    row = AuthActionToken(
        user_id=user.id,
        purpose=purpose,
        token_hash=hash_session_token(plain_token),
        expires_at=now + timedelta(minutes=get_settings().action_token_ttl_minutes),
        metadata_json=metadata or {},
    )
    db.add(row)
    db.flush()
    return plain_token, row


def consume_action_token(db: Session, token: str, purpose: str) -> tuple[User, AuthActionToken]:
    now = utcnow()
    token_hash = hash_session_token(token)
    consume_result = db.execute(
        update(AuthActionToken)
        .where(
            AuthActionToken.token_hash == token_hash,
            AuthActionToken.purpose == purpose,
            AuthActionToken.consumed_at.is_(None),
            AuthActionToken.expires_at > now,
        )
        .values(consumed_at=now)
    )
    if consume_result.rowcount != 1:
        raise ServiceError(400, "Action token is invalid or expired.")
    row = db.scalar(
        select(AuthActionToken).where(
            AuthActionToken.token_hash == token_hash,
            AuthActionToken.purpose == purpose,
        )
    )
    if row is None:  # Defensive: the successful update owns this row.
        raise ServiceError(400, "Action token is invalid or expired.")
    user = db.get(User, row.user_id)
    if user is None:
        raise ServiceError(400, "Action token is invalid or expired.")
    return user, row


def change_password(
    db: Session,
    context: AuthContext,
    *,
    current_password: str,
    new_password: str,
) -> None:
    if not verify_password(current_password, context.user.password_hash):
        raise ServiceError(400, "Current password is incorrect.")
    if verify_password(new_password, context.user.password_hash):
        raise ServiceError(422, "New password must be different from the current password.")
    context.user.password_hash = hash_password(new_password)
    context.user.must_change_password = False
    context.user.password_changed_at = utcnow()
    revoke_user_sessions(db, context.user.id, except_session_id=context.session.id)
    record_audit(
        db,
        action="auth.password_changed",
        company_id=context.user.company_id,
        user_id=context.user.id,
        entity_type="user",
        entity_id=context.user.id,
    )


def confirm_password_reset(db: Session, token: str, new_password: str) -> User:
    user, _row = consume_action_token(db, token, "password_reset")
    user.password_hash = hash_password(new_password)
    user.password_changed_at = utcnow()
    user.must_change_password = False
    revoke_user_sessions(db, user.id)
    record_audit(
        db,
        action="auth.password_reset_completed",
        company_id=user.company_id,
        user_id=user.id,
        entity_type="user",
        entity_id=user.id,
    )
    return user


def confirm_activation(db: Session, token: str, password: str | None = None) -> User:
    if not password:
        candidate = db.scalar(
            select(AuthActionToken).where(
                AuthActionToken.token_hash == hash_session_token(token),
                AuthActionToken.purpose == "activation",
                AuthActionToken.consumed_at.is_(None),
                AuthActionToken.expires_at > utcnow(),
            )
        )
        if candidate and candidate.metadata_json.get("password_required"):
            raise ServiceError(422, "A new password is required to activate this account.")
    user, row = consume_action_token(db, token, "activation")
    if password:
        user.password_hash = hash_password(password)
        user.password_changed_at = utcnow()
    user.must_change_password = False
    record_audit(
        db,
        action="auth.activation_completed",
        company_id=user.company_id,
        user_id=user.id,
        entity_type="user",
        entity_id=user.id,
    )
    return user


def require_permission(context: AuthContext, permission: str) -> None:
    if permission not in context.permissions:
        raise ServiceError(403, f"Missing required permission: {permission}")


def list_roles(db: Session, company_id: str | None) -> list[Role]:
    return list(db.scalars(select(Role).where(Role.company_id == company_id).order_by(Role.name)))


def role_permissions(db: Session, role_id: str) -> list[str]:
    query = (
        select(Permission.key)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == role_id)
        .order_by(Permission.key)
    )
    return list(db.scalars(query).all())


def list_settings(db: Session, company_id: str | None) -> list[Setting]:
    query = select(Setting).where(Setting.company_id == company_id).order_by(Setting.key)
    return list(db.scalars(query).all())


def upsert_setting(
    db: Session,
    *,
    company_id: str | None,
    key: str,
    value: dict[str, Any],
    user_id: str,
) -> Setting:
    setting = db.scalar(select(Setting).where(Setting.company_id == company_id, Setting.key == key))
    if setting is None:
        setting = Setting(company_id=company_id, key=key, value=value)
        db.add(setting)
    else:
        setting.value = value
    db.flush()
    db.refresh(setting)
    record_audit(
        db,
        action="settings.updated",
        company_id=company_id,
        user_id=user_id,
        entity_type="setting",
        entity_id=key,
        metadata={"key": key},
    )
    return setting


def list_audit_logs(db: Session, company_id: str | None, limit: int = 100) -> list[AuditLog]:
    query = (
        select(AuditLog)
        .where(AuditLog.company_id == company_id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    return list(db.scalars(query).all())
