import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from erp.packages.core.db.models import Base, Company, Permission, Role, RolePermission
from erp.packages.core.services import (
    ADMINISTRATOR_ROLE_NAME,
    MANAGER_CORE_PERMISSIONS,
    MANAGER_ROLE_NAME,
    VENDOR_ROLE_NAME,
    VENDOR_SELF_SERVICE_PERMISSIONS,
    seed_default_roles,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()

def test_seed_default_roles_creates_roles(db):
    company = Company(name="Test Co", slug="test-co", status="active")
    db.add(company)
    db.flush()
    
    seed_default_roles(db, company.id)
    
    roles = db.scalars(select(Role).where(Role.company_id == company.id)).all()
    role_names = {r.name for r in roles}
    assert ADMINISTRATOR_ROLE_NAME in role_names
    assert VENDOR_ROLE_NAME in role_names
    assert "Rider" in role_names
    assert "Manager" in role_names

    # test idempotency
    seed_default_roles(db, company.id)
    roles_after = db.scalars(select(Role).where(Role.company_id == company.id)).all()
    assert len(roles) == len(roles_after)

    permission_rows = {
        role.name: {
            key
            for key in db.scalars(
                select(Permission.key)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .where(RolePermission.role_id == role.id)
            ).all()
        }
        for role in roles
    }
    assert permission_rows[MANAGER_ROLE_NAME] == set(MANAGER_CORE_PERMISSIONS)
    assert permission_rows[VENDOR_ROLE_NAME] == set(VENDOR_SELF_SERVICE_PERMISSIONS)

def test_seed_default_roles_tenant_isolation(db):
    c1 = Company(name="C1", slug="c1", status="active")
    c2 = Company(name="C2", slug="c2", status="active")
    db.add_all([c1, c2])
    db.flush()
    
    seed_default_roles(db, c1.id)
    
    c1_roles = db.scalars(select(Role).where(Role.company_id == c1.id)).all()
    c2_roles = db.scalars(select(Role).where(Role.company_id == c2.id)).all()
    assert len(c1_roles) == 4
    assert len(c2_roles) == 0

def test_seed_default_roles_does_not_overwrite_vendor(db):
    company = Company(name="C3", slug="c3", status="active")
    db.add(company)
    db.flush()
    
    vendor_role = Role(company_id=company.id, name=VENDOR_ROLE_NAME, description="Custom")
    db.add(vendor_role)
    db.flush()
    
    seed_default_roles(db, company.id)
    
    perms = list(
        db.scalars(select(RolePermission).where(RolePermission.role_id == vendor_role.id)).all()
    )
    assert len(perms) == 0


def test_seed_default_roles_does_not_overwrite_custom_manager(db):
    company = Company(name="C4", slug="c4", status="active")
    db.add(company)
    db.flush()

    manager_role = Role(company_id=company.id, name=MANAGER_ROLE_NAME, description="Custom")
    db.add(manager_role)
    db.flush()

    seed_default_roles(db, company.id)

    permissions = db.scalars(
        select(RolePermission).where(RolePermission.role_id == manager_role.id)
    ).all()
    assert permissions == []
