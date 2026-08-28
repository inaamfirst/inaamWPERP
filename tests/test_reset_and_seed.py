import os
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from erp.packages.core.db.base import Base
from erp.packages.core.db.models import (
    Company,
    Customer,
    CustomerAddress,
    DeliveryAssignment,
    DeliveryStatusHistory,
    NotificationTemplate,
    Order,
    OrderStatusHistory,
    Payment,
    Product,
    ProductCategoryLink,
    ProductChannelListing,
    ProductImage,
    Role,
    RolePermission,
    SupportContact,
    User,
    UserRole,
    Vendor,
    VendorInventoryBalance,
    VendorInventoryMovement,
    VendorProduct,
    VendorSettlement,
    VendorUser,
)
from erp.packages.core.security import verify_password

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "reset_and_seed_demo_data.py"


@pytest.fixture
def sqlite_db_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'test_demo.db'}"


@pytest.fixture
def postgres_db_url() -> str | None:
    return os.environ.get("ERP_TEST_POSTGRES_URL")


def run_script(db_url: str) -> None:
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        if session.query(Company).filter_by(slug="inaam").first() is None:
            session.add(Company(name="Demo Test Company", slug="inaam", status="active"))
            session.commit()
    engine.dispose()

    result = subprocess.run(
        ["python", str(SCRIPT_PATH), "--database-url", db_url, "--yes"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def verify_data(db_url: str) -> None:
    engine = create_engine(db_url)
    with sessionmaker(bind=engine)() as session:
        users = session.query(User).all()
        assert {user.username for user in users} == {
            "admin",
            "vendor1",
            "vendor2",
            "vendor3",
            "vendor4",
            "vendor5",
            "manager",
            "rider",
        }
        admin = next(user for user in users if user.username == "admin")
        manager = next(user for user in users if user.username == "manager")
        rider = next(user for user in users if user.username == "rider")
        assert verify_password("admin12345", admin.password_hash)
        assert verify_password("DemoManager123!", manager.password_hash)
        assert verify_password("DemoRider123!", rider.password_hash)
        assert all(
            verify_password("DemoVendor123!", user.password_hash)
            for user in users
            if user.username.startswith("vendor")
        )

        company = session.query(Company).filter_by(slug="inaam").one()
        roles = session.query(Role).filter_by(company_id=company.id).all()
        assert {role.name for role in roles} == {"Administrator", "Vendor", "Manager", "Rider"}
        role_permission_counts = {
            role.name: session.query(RolePermission).filter_by(role_id=role.id).count()
            for role in roles
        }
        assert role_permission_counts["Administrator"] > 0
        assert role_permission_counts["Vendor"] > 0
        assert role_permission_counts["Manager"] > 0
        assert role_permission_counts["Rider"] > 0

        vendors = session.query(Vendor).filter_by(company_id=company.id).all()
        assert len(vendors) == 5
        assert session.query(Product).filter_by(company_id=company.id).count() == 15
        assert session.query(ProductCategoryLink).filter_by(company_id=company.id).count() == 15
        assert session.query(ProductImage).filter_by(company_id=company.id).count() == 15
        assert session.query(ProductChannelListing).filter_by(company_id=company.id).count() == 15
        assert session.query(Customer).filter_by(company_id=company.id).count() == 5
        assert session.query(CustomerAddress).filter_by(company_id=company.id).count() == 5
        assert session.query(Order).filter_by(company_id=company.id).count() == 15
        assert session.query(Payment).filter_by(company_id=company.id).count() > 0
        assert session.query(OrderStatusHistory).filter_by(company_id=company.id).count() > 0
        assert session.query(SupportContact).filter_by(company_id=company.id).count() == 1
        assert session.query(NotificationTemplate).filter_by(company_id=company.id).count() == 1

        for vendor in vendors:
            vendor_user = session.query(VendorUser).filter_by(
                vendor_id=vendor.id, is_primary=True
            ).one()
            assert session.query(VendorProduct).filter_by(vendor_id=vendor.id).count() == 3
            assert session.query(VendorInventoryBalance).filter_by(vendor_id=vendor.id).count() == 3
            assert (
                session.query(VendorInventoryMovement)
                .filter_by(vendor_id=vendor.id)
                .count()
                == 3
            )
            assert session.query(VendorSettlement).filter_by(vendor_id=vendor.id).count() == 1
            assert session.query(UserRole).filter_by(user_id=vendor_user.user_id).count() == 1

        rider = session.query(User).filter_by(username="rider").one()
        deliveries = session.query(DeliveryAssignment).filter_by(rider_user_id=rider.id).all()
        assert len(deliveries) > 0
        assert {delivery.status for delivery in deliveries} <= {
            "assigned",
            "picked_up",
            "out_for_delivery",
            "delivered",
            "failed",
            "cancelled",
        }
        assert session.query(DeliveryStatusHistory).filter_by(company_id=company.id).count() > 0
        if engine.dialect.name == "sqlite":
            assert session.execute(text("PRAGMA foreign_key_check")).all() == []


def test_sqlite_reset_and_seed(sqlite_db_url: str) -> None:
    run_script(sqlite_db_url)
    verify_data(sqlite_db_url)
    # The reset must not accumulate users, vendors, or operational rows.
    run_script(sqlite_db_url)
    verify_data(sqlite_db_url)


def test_postgres_reset_and_seed(postgres_db_url: str | None) -> None:
    if not postgres_db_url:
        pytest.skip("ERP_TEST_POSTGRES_URL not set")
    run_script(postgres_db_url)
    verify_data(postgres_db_url)
    run_script(postgres_db_url)
    verify_data(postgres_db_url)
