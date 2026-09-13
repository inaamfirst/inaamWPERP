from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from erp.packages.core.db.base import Base
from erp.packages.core.db.models import (
    Company,
    Customer,
    Order,
    OrderItem,
    Permission,
    PushNotification,
    PushSubscription,
    Role,
    RolePermission,
    User,
    UserRole,
    Vendor,
    VendorUser,
    new_uuid,
)
from erp.packages.core.push_services import (
    enqueue_order_created,
    process_push_notifications,
    register_subscription,
)
from erp.packages.core.schemas import PushSubscriptionCreate


@dataclass(frozen=True)
class PushSettings:
    effective_push_enabled: bool = True
    push_vapid_public_key: str = "public"
    push_vapid_private_key: str = "private"
    push_vapid_subject: str = "mailto:test@example.com"
    push_ttl_seconds: int = 300
    push_max_attempts: int = 2


def make_session(tmp_path: Path) -> sessionmaker:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'push.db'}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def seed_order(db: Session) -> tuple[Company, Order, list[User]]:
    company = Company(id=new_uuid(), name="Push Company", slug="push-company", status="active")
    customer = Customer(
        id=new_uuid(), company_id=company.id, full_name="Private Customer", phone="+923000000000"
    )
    admin = User(
        id=new_uuid(), company_id=company.id, username="admin", password_hash="hash",
        account_status="active", is_active=True,
    )
    vendor_user_one = User(
        id=new_uuid(), company_id=company.id, username="vendor-one", password_hash="hash",
        account_status="active", is_active=True,
    )
    vendor_user_two = User(
        id=new_uuid(), company_id=company.id, username="vendor-two", password_hash="hash",
        account_status="active", is_active=True,
    )
    vendor_one = Vendor(
        id=new_uuid(), company_id=company.id, name="Vendor One", slug="vendor-one", status="active"
    )
    vendor_two = Vendor(
        id=new_uuid(), company_id=company.id, name="Vendor Two", slug="vendor-two", status="active"
    )
    admin_role = Role(id=new_uuid(), company_id=company.id, name="Administrator")
    vendor_role = Role(id=new_uuid(), company_id=company.id, name="Vendor")
    order_permission = Permission(id=new_uuid(), key="orders.view")
    vendor_permission = Permission(id=new_uuid(), key="vendor.orders.view")
    db.add_all([
        company, customer, admin, vendor_user_one, vendor_user_two, vendor_one, vendor_two,
        admin_role, vendor_role, order_permission, vendor_permission,
    ])
    db.flush()
    db.add_all([
        RolePermission(role_id=admin_role.id, permission_id=order_permission.id),
        RolePermission(role_id=vendor_role.id, permission_id=vendor_permission.id),
        UserRole(user_id=admin.id, role_id=admin_role.id),
        UserRole(user_id=vendor_user_one.id, role_id=vendor_role.id),
        UserRole(user_id=vendor_user_two.id, role_id=vendor_role.id),
        VendorUser(
            id=new_uuid(),
            company_id=company.id,
            vendor_id=vendor_one.id,
            user_id=vendor_user_one.id,
        ),
        VendorUser(
            id=new_uuid(),
            company_id=company.id,
            vendor_id=vendor_two.id,
            user_id=vendor_user_two.id,
        ),
    ])
    order = Order(
        id=new_uuid(), company_id=company.id, customer_id=customer.id,
        order_number="ORD-PUSH-1", status="pending", currency="PKR",
    )
    db.add(order)
    db.flush()
    db.add_all([
        OrderItem(
            id=new_uuid(), company_id=company.id, order_id=order.id, product_id=new_uuid(),
            vendor_id=vendor_one.id, name="Vendor One Item", quantity=1,
            unit_price_minor=100, line_total_minor=100,
        ),
        OrderItem(
            id=new_uuid(), company_id=company.id, order_id=order.id, product_id=new_uuid(),
            vendor_id=vendor_two.id, name="Vendor Two Item", quantity=1,
            unit_price_minor=200, line_total_minor=200,
        ),
    ])
    db.flush()
    return company, order, [admin, vendor_user_one, vendor_user_two]


def test_order_fanout_is_scoped_and_idempotent(tmp_path: Path, monkeypatch) -> None:
    from erp.packages.core import push_services

    monkeypatch.setattr(push_services, "get_settings", lambda: PushSettings())
    factory = make_session(tmp_path)
    with factory() as db:
        company, order, users = seed_order(db)
        enqueue_order_created(db, company_id=company.id, order=order)
        db.flush()
        rows = list(db.scalars(select(PushNotification)).all())
        assert {row.recipient_user_id for row in rows} == {user.id for user in users}
        assert len(rows) == 3
        assert {row.vendor_id for row in rows if row.vendor_id} == {
            next(
                item.vendor_id
                for item in db.scalars(select(OrderItem)).all()
                if item.name == "Vendor One Item"
            ),
            next(
                item.vendor_id
                for item in db.scalars(select(OrderItem)).all()
                if item.name == "Vendor Two Item"
            ),
        }
        enqueue_order_created(db, company_id=company.id, order=order)
        db.flush()
        assert len(list(db.scalars(select(PushNotification)).all())) == 3


def test_completed_pos_sale_uses_the_same_scoped_order_fanout(
    tmp_path: Path, monkeypatch
) -> None:
    from erp.packages.core import push_services

    monkeypatch.setattr(push_services, "get_settings", lambda: PushSettings())
    factory = make_session(tmp_path)
    with factory() as db:
        company, order, users = seed_order(db)
        order.sales_channel = "pos"
        order.order_source = "pos"
        enqueue_order_created(db, company_id=company.id, order=order)
        db.flush()
        rows = list(db.scalars(select(PushNotification)).all())
        # POS sales are still orders: all admins and only the involved vendors
        # are notified, never unrelated vendor accounts.
        assert {row.recipient_user_id for row in rows} == {user.id for user in users}
        assert {row.vendor_id for row in rows if row.vendor_id} == {
            item.vendor_id for item in db.scalars(select(OrderItem)).all() if item.vendor_id
        }
        assert {row.title for row in rows} == {"New POS sale"}


def test_subscription_registration_and_delivery(tmp_path: Path, monkeypatch) -> None:
    from erp.packages.core import push_services

    monkeypatch.setattr(push_services, "get_settings", lambda: PushSettings())
    sent: list[dict] = []
    monkeypatch.setattr(
        push_services,
        "send_web_push",
        lambda subscription, payload: sent.append(payload),
    )
    factory = make_session(tmp_path)
    with factory() as db:
        company, order, users = seed_order(db)
        subscription = register_subscription(
            db,
            company_id=company.id,
            user_id=users[0].id,
            payload=PushSubscriptionCreate(
                endpoint="https://push.example/subscription/1",
                keys={"p256dh": "p256dh-value-123456", "auth": "auth-value-123456"},
            ),
        )
        assert subscription.is_active is True
        enqueue_order_created(db, company_id=company.id, order=order)
        db.flush()
        stats = process_push_notifications(db)
        db.commit()
        assert stats["sent"] == 1
        assert sent[0]["data"]["order_id"] == order.id
        assert "Private Customer" not in str(sent[0])
        assert db.scalar(
            select(PushSubscription).where(PushSubscription.id == subscription.id)
        ).is_active
