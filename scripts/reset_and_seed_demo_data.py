"""Reset one ERP company and load a deterministic demo workspace.

The command deliberately does not create or upgrade a database schema. Run the
normal migration command first, then invoke this script with an explicit
confirmation because it removes tenant data.
"""

from __future__ import annotations

import argparse
import os
import random
import shutil
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from erp.packages.core import ledger_services
from erp.packages.core.db.models import (
    AccountingPeriod,
    AuditLog,
    AuthActionToken,
    AuthRefreshToken,
    AuthSession,
    BankAccount,
    Brand,
    CashBook,
    Category,
    Company,
    Customer,
    CustomerAddress,
    CustomerNote,
    CustomerTag,
    DeliveryAssignment,
    DeliveryStatusHistory,
    Expense,
    ExternalResourceMap,
    JournalEntry,
    JournalLine,
    LedgerJournal,
    LedgerLine,
    LedgerPeriod,
    LoginThrottle,
    NotificationDeliveryLog,
    NotificationQueue,
    NotificationTemplate,
    Order,
    OrderItem,
    OrderStatusHistory,
    Payment,
    Product,
    ProductCategoryLink,
    ProductChannelListing,
    ProductImage,
    ProductRelationship,
    ProductTagLink,
    ProductVariant,
    Role,
    RolePermission,
    StockMovement,
    StockReservation,
    SupportContact,
    SyncConflict,
    SyncOutbox,
    SyncRunLog,
    User,
    UserRole,
    Vendor,
    VendorInventoryBalance,
    VendorInventoryMovement,
    VendorLedgerEntry,
    VendorNotification,
    VendorOrderItem,
    VendorOrderItemStatusHistory,
    VendorProduct,
    VendorSettlement,
    VendorUser,
    Warehouse,
)
from erp.packages.core.schemas import (
    LedgerJournalCreate,
    LedgerLineCreate,
    VendorInventoryMovementCreate,
)
from erp.packages.core.security import hash_password
from erp.packages.core.services import seed_default_roles, utcnow

DEMO_VENDOR_PASSWORD = "DemoVendor123!"
DEMO_MANAGER_PASSWORD = "DemoManager123!"
DEMO_RIDER_PASSWORD = "DemoRider123!"
DEMO_ADMIN_PASSWORD = "admin12345"
DEMO_RANDOM_SEED = 20260813


def new_id() -> str:
    return str(uuid.uuid4())


def backup_database(database_url: str) -> None:
    """Create a recoverable SQLite copy; PostgreSQL is backed up externally."""
    if not database_url.startswith("sqlite:///"):
        return
    database_path = Path(database_url.removeprefix("sqlite:///"))
    if not database_path.exists():
        return
    backup_path = database_path.with_name(
        f"{database_path.name}.backup_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    )
    shutil.copy2(database_path, backup_path)
    print(f"Backed up SQLite database to {backup_path}")


def _delete_company_rows(session: Session, model: type, company_id: str) -> None:
    deleted = session.query(model).filter(model.company_id == company_id).delete(
        synchronize_session=False
    )
    if deleted:
        print(f"  Deleted {deleted} {model.__tablename__} row(s)")


def clear_company_data(session: Session, company: Company) -> None:
    """Delete only the selected tenant, preserving global permissions/company."""
    print(f"Clearing tenant data for {company.slug}...")
    company_id = company.id
    user_ids = [
        user.id for user in session.query(User).filter(User.company_id == company_id).all()
    ]

    # Children must be removed before their referenced orders, products,
    # vendors, users, and journals. This order works with PostgreSQL FKs too.
    company_models = [
        VendorOrderItemStatusHistory,
        OrderStatusHistory,
        DeliveryStatusHistory,
        NotificationDeliveryLog,
        DeliveryAssignment,
        Payment,
        VendorOrderItem,
        VendorSettlement,
        OrderItem,
        Order,
        StockMovement,
        StockReservation,
        VendorInventoryMovement,
        VendorInventoryBalance,
        LedgerLine,
        LedgerJournal,
        VendorLedgerEntry,
        VendorProduct,
        ProductCategoryLink,
        ProductTagLink,
        ProductRelationship,
        ProductVariant,
        ProductImage,
        ProductChannelListing,
        Product,
        Category,
        Brand,
        CustomerAddress,
        CustomerNote,
        CustomerTag,
        Customer,
        VendorNotification,
        NotificationQueue,
        NotificationTemplate,
        SupportContact,
        ExternalResourceMap,
        SyncOutbox,
        SyncConflict,
        SyncRunLog,
        JournalLine,
        JournalEntry,
        AccountingPeriod,
        LedgerPeriod,
        Expense,
        BankAccount,
        CashBook,
        VendorUser,
        Vendor,
        Warehouse,
    ]
    for model in company_models:
        _delete_company_rows(session, model, company_id)

    # Auth rows do not carry company_id, so scope them through the tenant's
    # users. Refresh tokens are deleted before their sessions.
    if user_ids:
        # Audit history is retained across demo resets, but its actor must not
        # reference users that are about to be replaced with new UUIDs.
        session.query(AuditLog).filter(
            AuditLog.company_id == company_id,
            AuditLog.user_id.in_(user_ids),
        ).update({AuditLog.user_id: None}, synchronize_session=False)
        session.query(AuthActionToken).filter(AuthActionToken.user_id.in_(user_ids)).delete(
            synchronize_session=False
        )
        session.query(AuthRefreshToken).filter(AuthRefreshToken.user_id.in_(user_ids)).delete(
            synchronize_session=False
        )
        session.query(AuthSession).filter(AuthSession.user_id.in_(user_ids)).delete(
            synchronize_session=False
        )
        session.query(UserRole).filter(UserRole.user_id.in_(user_ids)).delete(
            synchronize_session=False
        )

    # Remove all old tenant roles and their assignments, but retain the global
    # permission catalogue used by every company.
    role_ids = [
        role.id for role in session.query(Role).filter(Role.company_id == company_id).all()
    ]
    if role_ids:
        session.query(RolePermission).filter(RolePermission.role_id.in_(role_ids)).delete(
            synchronize_session=False
        )
        session.query(Role).filter(Role.id.in_(role_ids)).delete(synchronize_session=False)

    if user_ids:
        session.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session=False)
    # Login throttles are intentionally global and contain no tenant key in the
    # current schema; clearing them prevents stale demo login lockouts.
    session.query(LoginThrottle).delete(synchronize_session=False)
    session.flush()


def setup_roles_and_admin(session: Session, company: Company) -> User:
    seed_default_roles(session, company.id)
    admin = User(
        id=new_id(),
        company_id=company.id,
        username="admin",
        email="admin@demo.local",
        password_hash=hash_password(DEMO_ADMIN_PASSWORD),
        full_name="Demo Administrator",
        is_active=True,
        account_status="active",
        must_change_password=False,
        password_changed_at=utcnow(),
    )
    session.add(admin)
    session.flush()
    admin_role = session.query(Role).filter_by(company_id=company.id, name="Administrator").one()
    session.add(UserRole(user_id=admin.id, role_id=admin_role.id))
    session.flush()
    return admin


def seed_staff_accounts(session: Session, company: Company) -> tuple[User, User]:
    roles = {
        role.name: role
        for role in session.query(Role).filter(Role.company_id == company.id).all()
    }
    manager = User(
        id=new_id(),
        company_id=company.id,
        username="manager",
        email="manager@demo.local",
        password_hash=hash_password(DEMO_MANAGER_PASSWORD),
        full_name="Demo Manager",
        is_active=True,
        account_status="active",
        must_change_password=False,
        password_changed_at=utcnow(),
    )
    rider = User(
        id=new_id(),
        company_id=company.id,
        username="rider",
        email="rider@demo.local",
        password_hash=hash_password(DEMO_RIDER_PASSWORD),
        full_name="Demo Rider",
        is_active=True,
        account_status="active",
        must_change_password=False,
        password_changed_at=utcnow(),
    )
    session.add_all([manager, rider])
    session.flush()
    session.add_all(
        [
            UserRole(user_id=manager.id, role_id=roles["Manager"].id),
            UserRole(user_id=rider.id, role_id=roles["Rider"].id),
        ]
    )
    session.flush()
    return manager, rider


def seed_catalog(session: Session, company: Company) -> tuple[list[Vendor], list[Product]]:
    rng = random.Random(DEMO_RANDOM_SEED)
    vendors = [
        Vendor(
            id=new_id(),
            company_id=company.id,
            name=f"Demo Vendor {index}",
            slug=f"demo-vendor-{index}",
            contact_name=f"Vendor Contact {index}",
            email=f"vendor{index}@demo.local",
            phone=f"+9230000000{index:02d}",
            status="active",
            default_commission_bps=1000,
            metadata_json={"demo_seed": True},
        )
        for index in range(1, 6)
    ]
    categories = [
        Category(
            id=new_id(),
            company_id=company.id,
            name=f"Demo Category {index}",
            slug=f"demo-category-{index}",
            description="Seeded demo catalog category.",
        )
        for index in range(1, 4)
    ]
    brands = [
        Brand(
            id=new_id(),
            company_id=company.id,
            name=f"Demo Brand {index}",
            slug=f"demo-brand-{index}",
            description="Seeded demo catalog brand.",
        )
        for index in range(1, 4)
    ]
    session.add_all([*vendors, *categories, *brands])
    session.flush()

    products: list[Product] = []
    for vendor_index, vendor in enumerate(vendors, start=1):
        for product_index in range(1, 4):
            category = categories[(vendor_index + product_index) % len(categories)]
            brand = brands[(vendor_index + product_index) % len(brands)]
            product = Product(
                id=new_id(),
                company_id=company.id,
                vendor_id=vendor.id,
                category_id=category.id,
                brand_id=brand.id,
                name=f"Product {product_index} by {vendor.name}",
                slug=f"product-{vendor_index}-{product_index}",
                sku=f"DEMO-{vendor_index:02d}-{product_index:02d}",
                regular_price_minor=rng.randint(500, 5000) * 100,
                status="active",
                visibility="visible",
                manage_stock=True,
                stock_quantity=100,
                stock_status="instock",
                description="Seeded product for ERP workflow testing.",
                short_description="Demo product.",
                metadata_json={"demo_seed": True},
            )
            products.append(product)
            session.add(product)
            session.add(
                ProductCategoryLink(
                    id=new_id(),
                    company_id=company.id,
                    product_id=product.id,
                    category_id=category.id,
                    is_primary=True,
                )
            )
            session.add(
                ProductImage(
                    id=new_id(),
                    company_id=company.id,
                    product_id=product.id,
                    external_id=f"demo-image-{vendor_index}-{product_index}",
                    url=f"https://example.com/demo/{vendor_index}-{product_index}.jpg",
                    name="Demo product image",
                    alt_text=product.name,
                    sync_status="synced",
                )
            )
            session.add(
                ProductChannelListing(
                    id=new_id(),
                    company_id=company.id,
                    product_id=product.id,
                    vendor_id=vendor.id,
                    channel="woocommerce",
                    listing_status="published",
                    channel_sku=product.sku,
                    price_minor=product.regular_price_minor,
                    sync_status="synced",
                )
            )
    session.flush()
    return vendors, products


def seed_vendor_access(
    session: Session,
    company: Company,
    vendors: list[Vendor],
    products: list[Product],
) -> None:
    vendor_role = session.query(Role).filter_by(company_id=company.id, name="Vendor").one()
    for index, vendor in enumerate(vendors, start=1):
        user = User(
            id=new_id(),
            company_id=company.id,
            username=f"vendor{index}",
            email=f"vendor{index}@demo.local",
            password_hash=hash_password(DEMO_VENDOR_PASSWORD),
            full_name=vendor.name,
            is_active=True,
            account_status="active",
            must_change_password=False,
            password_changed_at=utcnow(),
        )
        session.add(user)
        session.flush()
        session.add_all(
            [
                VendorUser(
                    id=new_id(),
                    company_id=company.id,
                    vendor_id=vendor.id,
                    user_id=user.id,
                    role_name="vendor",
                    is_primary=True,
                ),
                UserRole(user_id=user.id, role_id=vendor_role.id),
            ]
        )
        for product in products:
            if product.vendor_id == vendor.id:
                session.add(
                    VendorProduct(
                        id=new_id(),
                        company_id=company.id,
                        vendor_id=vendor.id,
                        product_id=product.id,
                        ownership_type="vendor_owned",
                        approval_status="approved",
                        approved_by_id=session.query(User).filter_by(
                            company_id=company.id, username="admin"
                        ).one().id,
                        approved_at=utcnow(),
                        published_at=utcnow(),
                        metadata_json={"demo_seed": True},
                    )
                )
    session.flush()


def seed_support_data(session: Session, company: Company, admin: User) -> None:
    session.add(
        SupportContact(
            id=new_id(),
            company_id=company.id,
            label="Demo Support",
            role="support",
            phone="+923000000999",
            whatsapp_message="Hello, I need help with my ERP demo workspace.",
            working_hours="Mon-Sat 09:00-17:00",
            priority=1,
        )
    )
    template = NotificationTemplate(
        id=new_id(),
        company_id=company.id,
        channel="whatsapp",
        name="order_confirmation",
        language="en",
        body="Your demo order {{order_id}} has been confirmed.",
    )
    session.add(template)
    session.flush()
    session.add(
        NotificationQueue(
            id=new_id(),
            company_id=company.id,
            channel="whatsapp",
            template_id=template.id,
            recipient_phone="+923000000001",
            message_body="Your demo order ORD-DEMO-0001 has been confirmed.",
            status="queued",
            idempotency_key="demo-notification-order-1",
            created_by_id=admin.id,
            metadata_json={"demo_seed": True},
        )
    )


def seed_orders_and_deliveries(
    session: Session,
    company: Company,
    admin: User,
    rider: User,
    products: list[Product],
    warehouse: Warehouse,
) -> list[Order]:
    rng = random.Random(DEMO_RANDOM_SEED)
    customers: list[Customer] = []
    for index in range(1, 6):
        customer = Customer(
            id=new_id(),
            company_id=company.id,
            full_name=f"Demo Customer {index}",
            email=f"customer{index}@demo.local",
            phone=f"+9231000000{index:02d}",
            source_channel="demo",
            metadata_json={"demo_seed": True},
        )
        customers.append(customer)
        session.add(customer)
        session.flush()
        session.add(
            CustomerAddress(
                id=new_id(),
                company_id=company.id,
                customer_id=customer.id,
                label="Default",
                recipient_name=customer.full_name,
                phone=customer.phone,
                line1=f"{index} Demo Street",
                city="Demo City",
                state="Demo State",
                postal_code=f"7500{index}",
                country="PK",
                is_default=True,
            )
        )
        session.add(
            CustomerNote(
                id=new_id(),
                company_id=company.id,
                customer_id=customer.id,
                created_by_id=admin.id,
                note="Seeded demo customer note.",
            )
        )
        session.add(
            CustomerTag(
                id=new_id(),
                company_id=company.id,
                customer_id=customer.id,
                tag="demo",
            )
        )

    session.flush()
    orders: list[Order] = []
    status_sequences = [
        ["pending"],
        ["pending", "confirmed"],
        ["pending", "confirmed", "packing"],
        ["pending", "confirmed", "packing", "ready"],
        ["pending", "confirmed", "packing", "ready", "dispatched"],
        ["pending", "confirmed", "packing", "ready", "dispatched", "delivered"],
    ]
    end_date = datetime.now(UTC).replace(microsecond=0)
    for order_index in range(1, 16):
        customer = customers[(order_index - 1) % len(customers)]
        order_date = end_date - timedelta(days=30 - order_index)
        sequence = status_sequences[(order_index - 1) % len(status_sequences)]
        order = Order(
            id=new_id(),
            company_id=company.id,
            customer_id=customer.id,
            order_number=f"ORD-DEMO-{order_index:04d}",
            sales_channel="demo",
            order_source="demo_seed",
            status=sequence[-1],
            currency="PKR",
            payment_status="unpaid",
            metadata_json={"demo_seed": True},
            created_at=order_date,
            updated_at=order_date,
        )
        session.add(order)
        session.flush()
        session.add(
            OrderStatusHistory(
                id=new_id(),
                company_id=company.id,
                order_id=order.id,
                from_status=None,
                to_status="pending",
                changed_by_id=admin.id,
                reason="Demo order created.",
                created_at=order_date,
            )
        )
        for from_status, to_status in zip(sequence, sequence[1:], strict=False):
            session.add(
                OrderStatusHistory(
                    id=new_id(),
                    company_id=company.id,
                    order_id=order.id,
                    from_status=from_status,
                    to_status=to_status,
                    changed_by_id=admin.id,
                    reason="Demo workflow transition.",
                    created_at=order_date + timedelta(minutes=len(orders) + 1),
                )
            )

        total = 0
        selected_products = rng.sample(products, 2)
        for product in selected_products:
            quantity = 1 + ((order_index + len(orders)) % 3)
            line_total = quantity * product.regular_price_minor
            total += line_total
            order_item = OrderItem(
                id=new_id(),
                company_id=company.id,
                order_id=order.id,
                product_id=product.id,
                vendor_id=product.vendor_id,
                sku=product.sku,
                name=product.name,
                quantity=quantity,
                unit_price_minor=product.regular_price_minor,
                line_total_minor=line_total,
                metadata_json={"demo_seed": True},
            )
            session.add(order_item)
            session.flush()
            commission = line_total // 10
            session.add(
                VendorOrderItem(
                    id=new_id(),
                    company_id=company.id,
                    vendor_id=product.vendor_id,
                    order_id=order.id,
                    order_item_id=order_item.id,
                    product_id=product.id,
                    sku=product.sku,
                    name=product.name,
                    quantity=quantity,
                    unit_price_minor=product.regular_price_minor,
                    line_total_minor=line_total,
                    commission_bps=1000,
                    commission_minor=commission,
                    payable_minor=line_total - commission,
                    status="paid" if order.status == "delivered" else "pending",
                    metadata_json={"demo_seed": True},
                )
            )
            session.add(
                StockMovement(
                    id=new_id(),
                    company_id=company.id,
                    warehouse_id=warehouse.id,
                    product_id=product.id,
                    movement_type="sale",
                    quantity_delta=-quantity,
                    reference_type="order",
                    reference_id=order.id,
                    created_by_id=admin.id,
                    occurred_at=order_date,
                    metadata_json={"demo_seed": True},
                )
            )

        order.subtotal_minor = total
        order.total_minor = total
        if order.status in {"ready", "dispatched", "delivered"}:
            order.paid_minor = total
            order.payment_status = "paid"
            session.add(
                Payment(
                    id=new_id(),
                    company_id=company.id,
                    order_id=order.id,
                    amount_minor=total,
                    currency="PKR",
                    method="demo_card",
                    status="paid",
                    reference=f"DEMO-PAY-{order_index:04d}",
                    paid_at=order_date,
                    metadata_json={"demo_seed": True},
                    created_at=order_date,
                )
            )

        delivery_status = {
            "ready": "assigned",
            "dispatched": "out_for_delivery",
            "delivered": "delivered",
        }.get(order.status)
        if delivery_status:
            assignment = DeliveryAssignment(
                id=new_id(),
                company_id=company.id,
                order_id=order.id,
                rider_user_id=rider.id,
                status=delivery_status,
                recipient_name=customer.full_name,
                recipient_phone=customer.phone,
                address_line1=f"{customer.id[:8]} Demo Street",
                city="Demo City",
                postal_code="75000",
                country="PK",
                assigned_by_id=admin.id,
                created_at=order_date,
                updated_at=order_date,
            )
            if delivery_status == "out_for_delivery":
                assignment.picked_up_at = order_date + timedelta(hours=2)
                assignment.out_for_delivery_at = order_date + timedelta(hours=3)
            elif delivery_status == "delivered":
                assignment.picked_up_at = order_date + timedelta(hours=2)
                assignment.out_for_delivery_at = order_date + timedelta(hours=3)
                assignment.delivered_at = order_date + timedelta(hours=5)
            session.add(assignment)
            session.flush()
            delivery_history = [(None, "assigned")]
            if delivery_status in {"out_for_delivery", "delivered"}:
                delivery_history.append(("assigned", "picked_up"))
                delivery_history.append(("picked_up", "out_for_delivery"))
            if delivery_status == "delivered":
                delivery_history.append(("out_for_delivery", "delivered"))
            for history_index, (from_status, to_status) in enumerate(delivery_history):
                session.add(
                    DeliveryStatusHistory(
                        id=new_id(),
                        company_id=company.id,
                        delivery_assignment_id=assignment.id,
                        from_status=from_status,
                        to_status=to_status,
                        changed_by_id=admin.id,
                        reason="Demo delivery transition.",
                        created_at=order_date + timedelta(hours=history_index),
                    )
                )
        orders.append(order)
    session.flush()
    return orders


def seed_inventory(
    session: Session,
    company: Company,
    admin: User,
    products: list[Product],
    warehouse: Warehouse,
) -> None:
    for product in products:
        session.add(
            StockMovement(
                id=new_id(),
                company_id=company.id,
                warehouse_id=warehouse.id,
                product_id=product.id,
                movement_type="opening_balance",
                quantity_delta=100,
                reference_type="demo_seed",
                reference_id=product.id,
                created_by_id=admin.id,
                occurred_at=utcnow() - timedelta(days=31),
                metadata_json={"demo_seed": True},
            )
        )
        vendor = product.vendor_id
        ledger_services.record_vendor_inventory_movement(
            session,
            company_id=company.id,
            user_id=admin.id,
            payload=VendorInventoryMovementCreate(
                vendor_id=vendor,
                product_id=product.id,
                warehouse_id=warehouse.id,
                movement_type="opening_balance",
                quantity_delta=100,
                ownership_type="vendor_owned",
                unit_cost_minor=max(1, product.regular_price_minor // 2),
                source_type="demo_seed",
                source_id=f"opening-{product.id}",
                idempotency_key=f"demo-opening-{product.id}",
                occurred_at=utcnow() - timedelta(days=31),
                reason="Demo opening stock",
                metadata={"demo_seed": True},
            ),
        )
    session.flush()


def seed_vendor_finance(
    session: Session,
    company: Company,
    admin: User,
    vendors: list[Vendor],
) -> None:
    accounts = ledger_services.ensure_default_ledger_accounts(session, company.id)
    for index, vendor in enumerate(vendors, start=1):
        settlement = VendorSettlement(
            id=new_id(),
            company_id=company.id,
            vendor_id=vendor.id,
            settlement_number=f"DEMO-SET-{index:02d}",
            period_start_at=utcnow() - timedelta(days=30),
            period_end_at=utcnow(),
            status="paid",
            gross_minor=100000,
            commission_minor=10000,
            payable_minor=90000,
            paid_minor=90000,
            paid_at=utcnow(),
            metadata_json={"demo_seed": True},
        )
        session.add(settlement)
        ledger_services.post_journal(
            session,
            company_id=company.id,
            user_id=admin.id,
            payload=LedgerJournalCreate(
                source_type="demo_vendor_payable",
                source_id=vendor.id,
                idempotency_key=f"demo-payable-{vendor.id}",
                memo=f"Demo payable for {vendor.name}",
                posted_at=utcnow(),
                metadata={"demo_seed": True},
                lines=[
                    LedgerLineCreate(account_id=accounts["1010"].id, debit_minor=100000),
                    LedgerLineCreate(
                        account_id=accounts["2000"].id,
                        vendor_id=vendor.id,
                        credit_minor=90000,
                    ),
                    LedgerLineCreate(account_id=accounts["3000"].id, credit_minor=10000),
                ],
            ),
        )
    session.flush()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reset and seed ERP demo data")
    parser.add_argument(
        "--database-url",
        default="sqlite:///runtime_data/local_offline_erp.db",
        help="Migrated target database URL",
    )
    parser.add_argument("--company-slug", default="inaam", help="Target company slug")
    parser.add_argument("--dry-run", action="store_true", help="Rollback instead of committing")
    parser.add_argument("--yes", action="store_true", help="Skip destructive confirmation")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.yes and not args.dry_run:
        confirmation = input(
            "WARNING: this permanently replaces tenant data in "
            f"{args.database_url}. Continue? (y/N): "
        )
        if confirmation.strip().lower() != "y":
            print("Aborted.")
            raise SystemExit(1)

    backup_database(args.database_url)
    engine = create_engine(args.database_url)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as session:
        try:
            company = session.query(Company).filter_by(slug=args.company_slug).first()
            if company is None:
                raise RuntimeError(
                    f"Company '{args.company_slug}' was not found. "
                    "Run migrations and first-use setup first."
                )

            clear_company_data(session, company)
            admin = setup_roles_and_admin(session, company)
            _, rider = seed_staff_accounts(session, company)
            warehouse = Warehouse(
                id=new_id(),
                company_id=company.id,
                code="DEMO-WH",
                name="Demo Main Warehouse",
                address="Demo City",
            )
            session.add(warehouse)
            session.flush()
            vendors, products = seed_catalog(session, company)
            seed_vendor_access(session, company, vendors, products)
            seed_support_data(session, company, admin)
            seed_orders_and_deliveries(session, company, admin, rider, products, warehouse)
            seed_inventory(session, company, admin, products, warehouse)
            seed_vendor_finance(session, company, admin, vendors)

            if args.dry_run:
                session.rollback()
                print("Dry run complete; all changes rolled back.")
            else:
                session.commit()
                print("Demo data reset and seed completed successfully.")
        except Exception:
            session.rollback()
            raise
    engine.dispose()


if __name__ == "__main__":
    main()
