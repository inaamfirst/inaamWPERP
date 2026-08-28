from __future__ import annotations

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from erp.packages.core.db.models import (
    Company,
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
    Vendor,
    VendorUser,
)
from erp.packages.core.marketplace_services import update_vendor
from erp.packages.core.schemas import (
    CompanyCreate,
    CompanyUpdate,
    RoleCreate,
    RoleUpdate,
    UserCreate,
    UserUpdate,
    VendorUpdate,
)
from erp.packages.core.security import hash_password
from erp.packages.core.services import (
    ServiceError,
    declared_permissions,
    record_audit,
    revoke_user_sessions,
    unique_company_slug,
    utcnow,
)

COMPANY_STATUSES = {"active", "suspended"}


def require_company_admin_scope(user_company_id: str | None, target_company_id: str | None) -> None:
    if user_company_id is None:
        return
    if target_company_id != user_company_id:
        raise ServiceError(403, "Cannot manage a different company.")


def list_companies(db: Session, requester_company_id: str | None) -> list[Company]:
    if requester_company_id is None:
        query = select(Company).order_by(Company.name)
    else:
        query = select(Company).where(Company.id == requester_company_id)
    return list(db.scalars(query).all())


def get_company(db: Session, requester_company_id: str | None, company_id: str) -> Company:
    require_company_admin_scope(requester_company_id, company_id)
    company = db.get(Company, company_id)
    if company is None:
        raise ServiceError(404, "Company not found.")
    return company


def create_company(
    db: Session,
    *,
    requester_company_id: str | None,
    user_id: str,
    payload: CompanyCreate,
) -> Company:
    if requester_company_id is not None:
        raise ServiceError(403, "Only a platform administrator can create companies.")
    company = Company(
        name=payload.name,
        slug=unique_company_slug(db, payload.slug or payload.name),
        legal_name=payload.legal_name,
        status="active",
    )
    db.add(company)
    db.flush()
    from erp.packages.core.ledger_services import ensure_default_ledger_accounts

    ensure_default_ledger_accounts(db, company.id)
    db.refresh(company)
    record_audit(
        db,
        action="tenancy.company_created",
        company_id=company.id,
        user_id=user_id,
        entity_type="company",
        entity_id=company.id,
        metadata={"name": company.name},
    )
    return company


def update_company(
    db: Session,
    *,
    requester_company_id: str | None,
    user_id: str,
    company_id: str,
    payload: CompanyUpdate,
) -> Company:
    company = get_company(db, requester_company_id, company_id)
    if payload.name is not None:
        company.name = payload.name
    if payload.slug is not None:
        company.slug = unique_company_slug(db, payload.slug, exclude_company_id=company.id)
    if payload.legal_name is not None:
        company.legal_name = payload.legal_name
    if payload.status is not None:
        status = payload.status.strip().lower()
        if status not in COMPANY_STATUSES:
            raise ServiceError(422, f"Unsupported company status: {payload.status}.")
        if requester_company_id is not None and status != company.status:
            raise ServiceError(403, "Only a platform administrator can change company status.")
        company.status = status
    db.flush()
    db.refresh(company)
    record_audit(
        db,
        action="tenancy.company_updated",
        company_id=company.id,
        user_id=user_id,
        entity_type="company",
        entity_id=company.id,
        metadata={"status": company.status},
    )
    return company


def ensure_permissions(db: Session) -> dict[str, Permission]:
    existing = {row.key: row for row in db.scalars(select(Permission)).all()}
    for key in declared_permissions():
        if key not in existing:
            permission = Permission(key=key, description=f"Permission: {key}")
            db.add(permission)
            existing[key] = permission
    db.flush()
    return existing


def permissions_for_keys(db: Session, keys: list[str]) -> list[Permission]:
    declared = set(declared_permissions())
    invalid = sorted(set(keys) - declared)
    if invalid:
        raise ServiceError(422, f"Unknown permissions: {', '.join(invalid)}.")
    permission_rows = ensure_permissions(db)
    return [permission_rows[key] for key in keys]


def role_ids_for_company(db: Session, company_id: str | None, role_ids: list[str]) -> list[Role]:
    roles = list(
        db.scalars(
            select(Role).where(Role.company_id == company_id, Role.id.in_(role_ids))
        ).all()
    )
    if len(roles) != len(set(role_ids)):
        raise ServiceError(404, "One or more roles were not found for this company.")
    return roles


def set_user_roles(db: Session, user: User, role_ids: list[str]) -> None:
    role_ids_for_company(db, user.company_id, role_ids)
    db.query(UserRole).filter(UserRole.user_id == user.id).delete()
    db.add_all(UserRole(user_id=user.id, role_id=role_id) for role_id in sorted(set(role_ids)))


def list_users(db: Session, company_id: str | None) -> list[User]:
    return list(
        db.scalars(select(User).where(User.company_id == company_id).order_by(User.username)).all()
    )


def get_user(db: Session, company_id: str | None, user_id: str) -> User:
    user = db.scalar(select(User).where(User.company_id == company_id, User.id == user_id))
    if user is None:
        raise ServiceError(404, "User not found.")
    return user


def get_primary_vendor_for_user(
    db: Session,
    company_id: str | None,
    user_id: str,
) -> Vendor | None:
    links = list(
        db.scalars(
            select(VendorUser).where(
                VendorUser.company_id == company_id,
                VendorUser.user_id == user_id,
                func.lower(VendorUser.role_name) == "vendor",
            )
        ).all()
    )
    primary_links = [link for link in links if link.is_primary]
    if len(primary_links) > 1 or (not primary_links and len(links) > 1):
        return None
    if len(primary_links) != 1:
        return None
    vendor = db.scalar(
        select(Vendor).where(
            Vendor.company_id == company_id,
            Vendor.id == primary_links[0].vendor_id,
        )
    )
    if vendor is None:
        raise ServiceError(404, "Linked vendor profile not found.")
    return vendor


def create_user(
    db: Session,
    *,
    company_id: str | None,
    actor_user_id: str,
    payload: UserCreate,
) -> User:
    existing = db.scalar(
        select(User).where(User.company_id == company_id, User.username == payload.username)
    )
    if existing is not None:
        raise ServiceError(409, f"Username already exists: {payload.username}.")
    if payload.email:
        existing_email = db.scalar(select(User).where(User.email == payload.email))
        if existing_email is not None:
            raise ServiceError(409, f"Email already exists: {payload.email}.")
    user = User(
        company_id=company_id,
        username=payload.username,
        email=payload.email,
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        is_active=True,
        account_status=payload.account_status,
        must_change_password=payload.must_change_password,
        password_changed_at=utcnow(),
    )
    db.add(user)
    db.flush()
    if payload.role_ids:
        set_user_roles(db, user, payload.role_ids)
    db.refresh(user)
    record_audit(
        db,
        action="identity.user_created",
        company_id=company_id,
        user_id=actor_user_id,
        entity_type="user",
        entity_id=user.id,
        metadata={"username": user.username},
    )
    return user


def update_user(
    db: Session,
    *,
    company_id: str | None,
    actor_user_id: str,
    user_id: str,
    payload: UserUpdate,
) -> User:
    user = get_user(db, company_id, user_id)
    if payload.username is not None:
        existing_username = db.scalar(
            select(User).where(
                User.company_id == company_id,
                User.username == payload.username,
                User.id != user.id,
            )
        )
        if existing_username is not None:
            raise ServiceError(409, f"Username already exists: {payload.username}.")
    administrator_role = db.scalar(
        select(Role).where(
            Role.company_id == company_id,
            Role.name == "Administrator",
        )
    )
    is_administrator = bool(
        administrator_role
        and db.scalar(
            select(UserRole.user_id).where(
                UserRole.user_id == user.id,
                UserRole.role_id == administrator_role.id,
            )
        )
    )
    removes_administrator_role = bool(
        administrator_role
        and payload.role_ids is not None
        and administrator_role.id not in payload.role_ids
    )
    disables_administrator = payload.is_active is False or (
        payload.account_status is not None and payload.account_status != "active"
    )
    if is_administrator and (removes_administrator_role or disables_administrator):
        active_administrator_count = int(
            db.scalar(
                select(func.count(distinct(User.id)))
                .join(UserRole, UserRole.user_id == User.id)
                .where(
                    User.company_id == company_id,
                    User.account_status == "active",
                    User.is_active.is_(True),
                    UserRole.role_id == administrator_role.id,
                )
            )
            or 0
        )
        if active_administrator_count <= 1:
            raise ServiceError(409, "The final active administrator cannot be disabled.")
    if payload.username is not None:
        username_changed = payload.username != user.username
        user.username = payload.username
        if username_changed:
            revoke_user_sessions(db, user.id)
    if payload.email is not None:
        existing_email = db.scalar(
            select(User).where(User.email == payload.email, User.id != user.id)
        )
        if existing_email is not None:
            raise ServiceError(409, f"Email already exists: {payload.email}.")
        user.email = payload.email
    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.is_active is not None:
        user.is_active = payload.is_active
        if not payload.is_active:
            user.account_status = "stopped"
            revoke_user_sessions(db, user.id)
        elif user.account_status == "stopped":
            user.account_status = "active"
    if payload.account_status is not None:
        user.account_status = payload.account_status
        user.is_active = payload.account_status != "stopped"
        if payload.account_status != "active":
            revoke_user_sessions(db, user.id)
    if payload.must_change_password is not None:
        user.must_change_password = payload.must_change_password
    if payload.password is not None:
        user.password_hash = hash_password(payload.password)
        user.password_changed_at = utcnow()
        revoke_user_sessions(db, user.id)
    if payload.role_ids is not None:
        set_user_roles(db, user, payload.role_ids)
    db.flush()
    db.refresh(user)
    record_audit(
        db,
        action="identity.user_updated",
        company_id=company_id,
        user_id=actor_user_id,
        entity_type="user",
        entity_id=user.id,
        metadata={
            "username": user.username,
            "is_active": user.is_active,
            "account_status": user.account_status,
        },
    )
    return user


def update_user_and_vendor(
    db: Session,
    *,
    company_id: str | None,
    actor_user_id: str,
    user_id: str,
    user_payload: UserUpdate,
    vendor_payload: VendorUpdate | None = None,
) -> User:
    user = update_user(
        db,
        company_id=company_id,
        actor_user_id=actor_user_id,
        user_id=user_id,
        payload=user_payload,
    )
    if vendor_payload is not None:
        vendor = get_primary_vendor_for_user(db, company_id, user.id)
        if vendor is None:
            raise ServiceError(409, "This user does not have a linked vendor profile.")
        update_vendor(
            db,
            company_id=company_id,
            user_id=actor_user_id,
            vendor_id=vendor.id,
            payload=vendor_payload,
        )
    return user


def reset_user_password(
    db: Session,
    *,
    company_id: str | None,
    actor_user_id: str,
    user_id: str,
    password: str,
) -> User:
    user = get_user(db, company_id, user_id)
    user.password_hash = hash_password(password)
    user.must_change_password = True
    user.password_changed_at = utcnow()
    revoke_user_sessions(db, user.id)
    db.flush()
    record_audit(
        db,
        action="identity.user_password_reset",
        company_id=company_id,
        user_id=actor_user_id,
        entity_type="user",
        entity_id=user.id,
        metadata={"username": user.username},
    )
    return user


def create_role(
    db: Session,
    *,
    company_id: str | None,
    actor_user_id: str,
    payload: RoleCreate,
) -> Role:
    existing = db.scalar(
        select(Role).where(Role.company_id == company_id, Role.name == payload.name)
    )
    if existing is not None:
        raise ServiceError(409, f"Role already exists: {payload.name}.")
    role = Role(company_id=company_id, name=payload.name, description=payload.description)
    db.add(role)
    db.flush()
    for permission in permissions_for_keys(db, payload.permissions):
        db.add(RolePermission(role_id=role.id, permission_id=permission.id))
    db.flush()
    db.refresh(role)
    record_audit(
        db,
        action="identity.role_created",
        company_id=company_id,
        user_id=actor_user_id,
        entity_type="role",
        entity_id=role.id,
        metadata={"name": role.name},
    )
    return role


def update_role(
    db: Session,
    *,
    company_id: str | None,
    actor_user_id: str,
    role_id: str,
    payload: RoleUpdate,
) -> Role:
    role = db.scalar(select(Role).where(Role.company_id == company_id, Role.id == role_id))
    if role is None:
        raise ServiceError(404, "Role not found.")
    if payload.name is not None:
        existing = db.scalar(
            select(Role).where(
                Role.company_id == company_id,
                Role.name == payload.name,
                Role.id != role.id,
            )
        )
        if existing is not None:
            raise ServiceError(409, f"Role already exists: {payload.name}.")
        role.name = payload.name
    if payload.description is not None:
        role.description = payload.description
    if payload.permissions is not None:
        db.query(RolePermission).filter(RolePermission.role_id == role.id).delete()
        for permission in permissions_for_keys(db, payload.permissions):
            db.add(RolePermission(role_id=role.id, permission_id=permission.id))
    db.flush()
    db.refresh(role)
    record_audit(
        db,
        action="identity.role_updated",
        company_id=company_id,
        user_id=actor_user_id,
        entity_type="role",
        entity_id=role.id,
        metadata={"name": role.name},
    )
    return role
