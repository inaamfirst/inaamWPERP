from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from erp.packages.core.db.models import (
    Company,
    Role,
    User,
    UserRole,
    Vendor,
    VendorUser,
)
from erp.packages.core.schemas import AdminVendorAccountCreate, VendorRegistrationRequest
from erp.packages.core.security import generate_session_token, hash_password
from erp.packages.core.services import (
    VENDOR_SELF_SERVICE_PERMISSIONS,
    ServiceError,
    canonical_vendor_status,
    create_action_token,
    normalize_company_slug,
    record_audit,
    revoke_user_sessions,
    user_role_names,
    utcnow,
)

VENDOR_PORTAL_PERMISSIONS = VENDOR_SELF_SERVICE_PERMISSIONS
CANONICAL_VENDOR_STATUSES = {"active", "pending", "paused", "stopped"}


@dataclass(frozen=True)
class CreatedVendorAccount:
    vendor: Vendor
    user: User
    activation_token: str | None = None
    activation_expires_at: datetime | None = None


def unique_vendor_slug(db: Session, company_id: str, name: str) -> str:
    base = normalize_company_slug(name)[:150] or "vendor"
    slug = base
    suffix = 2
    while db.scalar(select(Vendor.id).where(Vendor.company_id == company_id, Vendor.slug == slug)):
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


def ensure_vendor_role(db: Session, company_id: str) -> Role:
    from erp.packages.core.services import seed_default_roles
    
    role = db.scalar(
        select(Role).where(Role.company_id == company_id, Role.name == "Vendor")
    )
    if role is None:
        seed_default_roles(db, company_id)
        role = db.scalar(
            select(Role).where(Role.company_id == company_id, Role.name == "Vendor")
        )
        
    _backfill_unambiguous_vendor_users(db, company_id=company_id, role=role)
    db.flush()
    return role


def _backfill_unambiguous_vendor_users(
    db: Session,
    *,
    company_id: str,
    role: Role,
) -> None:
    """Repair only explicit, unambiguous company-scoped vendor relationships."""

    links = list(
        db.scalars(
            select(VendorUser)
            .join(User, User.id == VendorUser.user_id)
            .where(
                VendorUser.company_id == company_id,
                User.company_id == company_id,
                func.lower(VendorUser.role_name) == "vendor",
            )
            .order_by(VendorUser.user_id, VendorUser.created_at, VendorUser.id)
        ).all()
    )
    links_by_user: dict[str, list[VendorUser]] = {}
    for link in links:
        links_by_user.setdefault(link.user_id, []).append(link)

    assigned_user_ids = set(
        db.scalars(select(UserRole.user_id).where(UserRole.role_id == role.id)).all()
    )
    for user_id, user_links in links_by_user.items():
        primary_links = [link for link in user_links if link.is_primary]
        if len(user_links) == 1 and not primary_links:
            user_links[0].is_primary = True
            primary_links = user_links
        if len(primary_links) != 1:
            # Multiple or missing primaries are intentionally left unresolved.
            continue
        if user_id not in assigned_user_ids:
            db.add(UserRole(user_id=user_id, role_id=role.id))
            assigned_user_ids.add(user_id)


def validate_new_identity(
    db: Session,
    *,
    company_id: str,
    username: str,
    email: str | None,
) -> None:
    if db.scalar(select(User.id).where(User.company_id == company_id, User.username == username)):
        raise ServiceError(409, "Registration could not be completed.")
    if email and db.scalar(select(User.id).where(User.email == email)):
        raise ServiceError(409, "Registration could not be completed.")


def register_public_vendor(
    db: Session,
    payload: VendorRegistrationRequest,
) -> CreatedVendorAccount:
    company = db.scalar(
        select(Company).where(
            Company.slug == normalize_company_slug(payload.workspace_slug),
            Company.status == "active",
        )
    )
    if company is None:
        raise ServiceError(404, "Workspace was not found.")
    validate_new_identity(
        db,
        company_id=company.id,
        username=payload.username,
        email=payload.email,
    )
    vendor = Vendor(
        company_id=company.id,
        name=payload.business_name,
        slug=unique_vendor_slug(db, company.id, payload.business_name),
        contact_name=payload.contact_name,
        email=payload.email,
        phone=payload.phone,
        status="pending",
    )
    user = User(
        company_id=company.id,
        username=payload.username,
        email=payload.email,
        full_name=payload.contact_name,
        password_hash=hash_password(payload.password),
        is_active=True,
        account_status="pending",
        must_change_password=False,
        password_changed_at=utcnow(),
    )
    db.add_all([vendor, user])
    db.flush()
    role = ensure_vendor_role(db, company.id)
    db.add_all(
        [
            VendorUser(
                company_id=company.id,
                vendor_id=vendor.id,
                user_id=user.id,
                role_name="vendor",
                is_primary=True,
            ),
            UserRole(user_id=user.id, role_id=role.id),
        ]
    )
    record_audit(
        db,
        action="marketplace.vendor_registered",
        company_id=company.id,
        user_id=user.id,
        entity_type="vendor",
        entity_id=vendor.id,
        metadata={"source": "public", "status": "pending"},
    )
    db.flush()
    return CreatedVendorAccount(vendor=vendor, user=user)


def create_admin_vendor_account(
    db: Session,
    *,
    company_id: str,
    actor_user_id: str,
    payload: AdminVendorAccountCreate,
) -> CreatedVendorAccount:
    validate_new_identity(
        db,
        company_id=company_id,
        username=payload.username,
        email=payload.email,
    )
    if not payload.use_activation and not payload.password:
        raise ServiceError(422, "A temporary password is required when activation is disabled.")
    if payload.use_activation and not payload.email:
        raise ServiceError(422, "An email address is required for activation onboarding.")
    if payload.use_activation and payload.password:
        raise ServiceError(422, "Choose activation or temporary-password onboarding, not both.")
    # A random, unreturned password makes an activation-only account impossible
    # to use until the one-time setup link is consumed.
    initial_password = payload.password or generate_session_token()
    vendor = Vendor(
        company_id=company_id,
        name=payload.business_name,
        slug=unique_vendor_slug(db, company_id, payload.business_name),
        contact_name=payload.contact_name,
        email=payload.email,
        phone=payload.phone,
        status="active",
        default_commission_bps=payload.default_commission_bps,
    )
    user = User(
        company_id=company_id,
        username=payload.username,
        email=payload.email,
        full_name=payload.contact_name,
        password_hash=hash_password(initial_password),
        is_active=True,
        account_status="active",
        must_change_password=True,
        password_changed_at=utcnow() if payload.password else None,
    )
    db.add_all([vendor, user])
    db.flush()
    role = ensure_vendor_role(db, company_id)
    db.add_all(
        [
            VendorUser(
                company_id=company_id,
                vendor_id=vendor.id,
                user_id=user.id,
                role_name="vendor",
                is_primary=True,
            ),
            UserRole(user_id=user.id, role_id=role.id),
        ]
    )
    activation_token = None
    activation_expires_at = None
    if payload.use_activation:
        activation_token, token_row = create_action_token(
            db,
            user,
            "activation",
            metadata={
                "created_by": actor_user_id,
                "password_required": payload.password is None,
            },
        )
        activation_expires_at = token_row.expires_at
    record_audit(
        db,
        action="marketplace.vendor_account_created",
        company_id=company_id,
        user_id=actor_user_id,
        entity_type="vendor",
        entity_id=vendor.id,
        metadata={"source": "administrator", "activation": payload.use_activation},
    )
    db.flush()
    return CreatedVendorAccount(
        vendor=vendor,
        user=user,
        activation_token=activation_token,
        activation_expires_at=activation_expires_at,
    )


def change_vendor_status(
    db: Session,
    *,
    company_id: str,
    actor_user_id: str,
    vendor_id: str,
    status: str,
    reason: str | None = None,
) -> Vendor:
    normalized = canonical_vendor_status(status)
    if normalized not in CANONICAL_VENDOR_STATUSES:
        raise ServiceError(422, "Unsupported vendor status.")
    vendor = db.scalar(
        select(Vendor).where(Vendor.company_id == company_id, Vendor.id == vendor_id)
    )
    if vendor is None:
        raise ServiceError(404, "Vendor not found.")
    previous_stored = vendor.status
    previous = canonical_vendor_status(previous_stored)
    vendor.status = normalized
    links = list(
        db.scalars(
            select(VendorUser).where(
                VendorUser.company_id == company_id, VendorUser.vendor_id == vendor.id
            )
        ).all()
    )
    affected_users: list[User] = []
    for link in links:
        if not link.is_primary or link.role_name.strip().lower() != "vendor":
            continue
        user = db.scalar(
            select(User).where(User.id == link.user_id, User.company_id == company_id)
        )
        if user is None:
            continue
        roles = user_role_names(db, user.id)
        if "Vendor" not in roles or "Administrator" in roles:
            continue
        affected_users.append(user)

    if normalized == "active" and previous == "pending":
        for user in affected_users:
            if user.account_status == "pending":
                user.account_status = "active"
    elif normalized != "active":
        for user in affected_users:
            revoke_user_sessions(db, user.id)

    if normalized == "active" and previous == "pending":
        transition = "approved"
    elif normalized == "active" and previous in {"paused", "stopped"}:
        transition = "reactivated"
    else:
        transition = normalized
    record_audit(
        db,
        action=f"marketplace.vendor_{transition}",
        company_id=company_id,
        user_id=actor_user_id,
        entity_type="vendor",
        entity_id=vendor.id,
        metadata={
            "previous_status": previous_stored,
            "previous_access_status": previous,
            "status": normalized,
            "reason": reason,
        },
    )
    db.flush()
    return vendor


def find_password_reset_user(
    db: Session,
    *,
    username_or_email: str,
    workspace_slug: str,
) -> User | None:
    company = db.scalar(
        select(Company).where(
            Company.slug == normalize_company_slug(workspace_slug),
            Company.status == "active",
        )
    )
    if company is None:
        return None
    return db.scalar(
        select(User).where(
            User.company_id == company.id,
            or_(User.username == username_or_email, User.email == username_or_email),
        )
    )
