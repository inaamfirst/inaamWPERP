import os
import random
import re
import sys
import uuid
from datetime import UTC, datetime, timedelta

# Ensure erp can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

from erp.packages.core import ledger_services
from erp.packages.core.db.models import (
    Company,
    Customer,
    LedgerJournal,
    Order,
    OrderItem,
    Permission,
    Product,
    Role,
    RolePermission,
    StockMovement,
    User,
    UserRole,
    Vendor,
    VendorInventoryBalance,
    VendorOrderItem,
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
from erp.packages.core.services import utcnow
from erp.packages.core.vendor_auth_services import ensure_vendor_role

DEMO_VENDOR_PASSWORD = "DemoVendor123!"
DEMO_VENDOR_VISIBILITY_ROLE = "Demo Vendor Visibility"
DEMO_VENDOR_READ_PERMISSIONS = frozenset(
    {
        "vendor.ledger.view",
        "vendor.stock.view",
        "vendor.reports.view",
    }
)


def new_id():
    return str(uuid.uuid4())


def slugify_username(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "vendor"


def unique_username(base: str, existing: set[str]) -> str:
    candidate = base
    suffix = 2
    while candidate in existing:
        candidate = f"{base}-{suffix}"
        suffix += 1
    existing.add(candidate)
    return candidate


def ensure_demo_vendor_visibility_role(session, company):
    """Grant demo accounts their own stock, finance, and report read views.

    The standard Vendor role deliberately remains limited to the core portal
    pages.  A separate role keeps this demo-only convenience explicit while
    preserving the same vendor-level scoping enforced by the API.
    """
    role = (
        session.query(Role)
        .filter_by(company_id=company.id, name=DEMO_VENDOR_VISIBILITY_ROLE)
        .first()
    )
    if role is None:
        role = Role(
            id=new_id(),
            company_id=company.id,
            name=DEMO_VENDOR_VISIBILITY_ROLE,
            description="Additional read-only portal views for seeded demo vendors.",
        )
        session.add(role)
        session.flush()

    permissions = (
        session.query(Permission)
        .filter(Permission.key.in_(DEMO_VENDOR_READ_PERMISSIONS))
        .all()
    )
    found = {permission.key for permission in permissions}
    missing = DEMO_VENDOR_READ_PERMISSIONS - found
    if missing:
        raise RuntimeError(f"Required vendor demo permissions are missing: {sorted(missing)}")
    assigned_ids = {
        row.permission_id
        for row in session.query(RolePermission).filter_by(role_id=role.id).all()
    }
    for permission in permissions:
        if permission.id not in assigned_ids:
            session.add(RolePermission(role_id=role.id, permission_id=permission.id))
    session.flush()
    return role


def seed_demo_vendor_access(session, company, vendors, products):
    print("Backfilling vendor login access and vendor-product assignments...")

    vendor_role = ensure_vendor_role(session, company.id)
    visibility_role = ensure_demo_vendor_visibility_role(session, company)
    session.flush()

    existing_usernames = {
        row[0]
        for row in session.query(User.username).filter(User.company_id == company.id).all()
    }
    existing_emails = {
        row[0]
        for row in session.query(User.email).filter(User.email.isnot(None)).all()
    }
    admin_user = (
        session.query(User)
        .filter_by(company_id=company.id, username="admin")
        .first()
    )
    approver_id = admin_user.id if admin_user else None

    created_users = 0
    updated_users = 0
    created_vendor_products = 0

    for vendor in vendors:
        # Demo vendors should be immediately usable in the desktop and API.
        vendor.status = "active"

        links = (
            session.query(VendorUser)
            .filter_by(company_id=company.id, vendor_id=vendor.id)
            .order_by(
                VendorUser.is_primary.desc(),
                VendorUser.created_at.asc(),
                VendorUser.id.asc(),
            )
            .all()
        )

        user = None
        if links:
            for index, link in enumerate(links):
                link.is_primary = index == 0
                link.role_name = "vendor"
            user = session.query(User).filter_by(id=links[0].user_id).first()

        if user is None:
            username = unique_username(
                slugify_username(vendor.slug or vendor.name),
                existing_usernames,
            )
            email = f"{username}@demo.local"
            if email in existing_emails:
                email = None
            user = User(
                id=new_id(),
                company_id=company.id,
                username=username,
                email=email,
                password_hash=hash_password(DEMO_VENDOR_PASSWORD),
                full_name=vendor.contact_name or vendor.name,
                is_active=True,
                account_status="active",
                must_change_password=False,
                password_changed_at=utcnow(),
            )
            session.add(user)
            session.flush()
            session.add(
                VendorUser(
                    id=new_id(),
                    company_id=company.id,
                    vendor_id=vendor.id,
                    user_id=user.id,
                    role_name="vendor",
                    is_primary=True,
                )
            )
            session.add(UserRole(user_id=user.id, role_id=vendor_role.id))
            session.add(UserRole(user_id=user.id, role_id=visibility_role.id))
            created_users += 1
        else:
            user.is_active = True
            user.account_status = "active"
            user.must_change_password = False
            user.password_hash = hash_password(DEMO_VENDOR_PASSWORD)
            user.password_changed_at = utcnow()
            if not user.full_name:
                user.full_name = vendor.contact_name or vendor.name
            if not user.email:
                generated_email = f"{slugify_username(user.username)}@demo.local"
                if generated_email not in existing_emails:
                    user.email = generated_email
                    existing_emails.add(generated_email)
            if not session.query(UserRole).filter_by(
                user_id=user.id,
                role_id=vendor_role.id,
            ).first():
                session.add(UserRole(user_id=user.id, role_id=vendor_role.id))
            if not session.query(UserRole).filter_by(
                user_id=user.id,
                role_id=visibility_role.id,
            ).first():
                session.add(UserRole(user_id=user.id, role_id=visibility_role.id))
            updated_users += 1

        vendor_product_rows = (
            session.query(VendorProduct)
            .filter_by(company_id=company.id, vendor_id=vendor.id)
            .all()
        )
        vendor_product_ids = {row.product_id for row in vendor_product_rows}
        for assignment in vendor_product_rows:
            # Inventory is seeded only for vendor-owned demo products, so keep
            # the product policy aligned with the generated catalogue.
            assignment.ownership_type = "vendor_owned"
            assignment.approval_status = "approved"
            assignment.approved_by_id = approver_id
            assignment.approved_at = assignment.approved_at or utcnow()
            assignment.published_at = assignment.published_at or utcnow()
        for product in products:
            if product.vendor_id != vendor.id or product.id in vendor_product_ids:
                continue
            session.add(
                VendorProduct(
                    id=new_id(),
                    company_id=company.id,
                    vendor_id=vendor.id,
                    product_id=product.id,
                    ownership_type="vendor_owned",
                    approval_status="approved",
                    approved_by_id=approver_id,
                    approved_at=utcnow(),
                    published_at=utcnow(),
                    metadata_json={"demo_seed": True},
                )
            )
            created_vendor_products += 1

    session.commit()
    print(
        "Vendor access backfill complete: "
        f"{created_users} user(s) created, {updated_users} user(s) normalized, "
        f"{created_vendor_products} vendor-product assignment(s) added."
    )
    print(f"Demo vendor password for created and normalized accounts: {DEMO_VENDOR_PASSWORD}")


def seed_demo_vendor_inventory(session, company, vendors, products, warehouse, user_id):
    """Create an opening stock record and a matching sale record per product.

    This is idempotent, so it fills older demo databases without changing real
    vendor inventory that has already been entered through the application.
    """
    created_movements = 0
    for vendor in vendors:
        vendor_products = [product for product in products if product.vendor_id == vendor.id]
        for product in vendor_products:
            existing = session.query(VendorInventoryBalance).filter_by(
                company_id=company.id,
                vendor_id=vendor.id,
                product_id=product.id,
                warehouse_id=warehouse.id,
                variant_key="",
            ).first()
            if existing is not None:
                continue

            sold_quantity = sum(
                int(row.quantity or 0)
                for row in session.query(VendorOrderItem)
                .filter_by(company_id=company.id, vendor_id=vendor.id, product_id=product.id)
                .all()
            )
            opening_quantity = max(100, sold_quantity + 20)
            unit_cost = max(1, int(product.regular_price_minor or 100) // 2)
            opening_key = f"demo-vendor-opening:{vendor.id}:{product.id}:{warehouse.id}"
            ledger_services.record_vendor_inventory_movement(
                session,
                company_id=company.id,
                user_id=user_id,
                payload=VendorInventoryMovementCreate(
                    vendor_id=vendor.id,
                    product_id=product.id,
                    warehouse_id=warehouse.id,
                    movement_type="opening_balance",
                    quantity_delta=opening_quantity,
                    ownership_type="vendor_owned",
                    unit_cost_minor=unit_cost,
                    source_type="demo_seed",
                    source_id=f"opening-{product.id}",
                    idempotency_key=opening_key,
                    occurred_at=utcnow() - timedelta(days=30),
                    reason="Demo opening stock",
                    metadata={"demo_seed": True},
                ),
            )
            created_movements += 1
            if sold_quantity:
                ledger_services.record_vendor_inventory_movement(
                    session,
                    company_id=company.id,
                    user_id=user_id,
                    payload=VendorInventoryMovementCreate(
                        vendor_id=vendor.id,
                        product_id=product.id,
                        warehouse_id=warehouse.id,
                        movement_type="sale",
                        quantity_delta=-sold_quantity,
                        ownership_type="vendor_owned",
                        unit_cost_minor=unit_cost,
                        source_type="demo_seed",
                        source_id=f"sales-{product.id}",
                        idempotency_key=f"demo-vendor-sales:{vendor.id}:{product.id}:{warehouse.id}",
                        occurred_at=utcnow(),
                        reason="Demo sales already reflected in vendor orders",
                        metadata={"demo_seed": True},
                    ),
                )
                created_movements += 1
    session.commit()
    print(f"Vendor inventory backfill complete: {created_movements} movement(s) added.")


def seed_demo_vendor_ledger(session, company, vendors, user_id):
    """Backfill a paid payable cycle so each vendor's Finance view has data."""
    accounts = ledger_services.ensure_default_ledger_accounts(session, company.id)
    created_journals = 0
    for vendor in vendors:
        totals = session.query(
            func.coalesce(func.sum(VendorOrderItem.line_total_minor), 0),
            func.coalesce(func.sum(VendorOrderItem.commission_minor), 0),
            func.coalesce(func.sum(VendorOrderItem.payable_minor), 0),
        ).filter_by(company_id=company.id, vendor_id=vendor.id).one()
        gross, commission, payable = (int(value or 0) for value in totals)
        if gross <= 0 or payable < 0:
            continue

        accrual_key = f"demo-vendor-payable:{vendor.id}"
        if not session.query(LedgerJournal).filter_by(
            company_id=company.id, idempotency_key=accrual_key
        ).first():
            ledger_services.post_journal(
                session,
                company_id=company.id,
                user_id=user_id,
                payload=LedgerJournalCreate(
                    source_type="demo_vendor_payable",
                    source_id=vendor.id,
                    idempotency_key=accrual_key,
                    memo=f"Demo payable accrued for {vendor.name}",
                    posted_at=utcnow() - timedelta(days=1),
                    metadata={"demo_seed": True, "vendor_id": vendor.id},
                    lines=[
                        LedgerLineCreate(account_id=accounts["1010"].id, debit_minor=gross),
                        LedgerLineCreate(
                            account_id=accounts["2000"].id,
                            vendor_id=vendor.id,
                            credit_minor=payable,
                        ),
                        LedgerLineCreate(account_id=accounts["3000"].id, credit_minor=commission),
                    ],
                ),
            )
            created_journals += 1
        if payable:
            payment_key = f"demo-vendor-settlement:{vendor.id}"
            if not session.query(LedgerJournal).filter_by(
                company_id=company.id, idempotency_key=payment_key
            ).first():
                ledger_services.post_journal(
                    session,
                    company_id=company.id,
                    user_id=user_id,
                    payload=LedgerJournalCreate(
                        source_type="demo_vendor_settlement",
                        source_id=vendor.id,
                        idempotency_key=payment_key,
                        memo=f"Demo settlement paid to {vendor.name}",
                        posted_at=utcnow(),
                        metadata={"demo_seed": True, "vendor_id": vendor.id},
                        lines=[
                            LedgerLineCreate(
                                account_id=accounts["2000"].id,
                                vendor_id=vendor.id,
                                debit_minor=payable,
                            ),
                            LedgerLineCreate(account_id=accounts["1010"].id, credit_minor=payable),
                        ],
                    ),
                )
                created_journals += 1
    session.commit()
    print(f"Vendor ledger backfill complete: {created_journals} journal(s) added.")


def run():
    db_path = "sqlite:///runtime_data/local_offline_erp.db"
    if not os.path.exists("runtime_data/local_offline_erp.db"):
        db_path = "sqlite:///../runtime_data/local_offline_erp.db"

    engine = create_engine(db_path)
    Session = sessionmaker(bind=engine)
    session = Session()

    print("Starting demo data generation...")

    company = session.query(Company).first()
    if not company:
        company = Company(id=new_id(), name="Demo Company", slug="demo-company")
        session.add(company)
        session.commit()

    warehouse = session.query(Warehouse).filter_by(company_id=company.id).first()
    if not warehouse:
        warehouse = Warehouse(
            id=new_id(),
            company_id=company.id,
            code="WH1",
            name="Main Warehouse",
        )
        session.add(warehouse)
        session.commit()

    vendors = session.query(Vendor).filter_by(company_id=company.id).all()
    if not vendors:
        print("No vendors found. Creating demo vendors...")
        for i in range(1, 4):
            v = Vendor(
                id=new_id(),
                company_id=company.id,
                name=f"Demo Vendor {i}",
                slug=f"demo-vendor-{i}",
                status="approved",
                default_commission_bps=1000,
            )
            session.add(v)
            vendors.append(v)
        session.commit()

    customers = session.query(Customer).filter_by(company_id=company.id).all()
    if not customers:
        for i in range(1, 6):
            c = Customer(
                id=new_id(),
                company_id=company.id,
                full_name=f"Demo Customer {i}",
                email=f"customer{i}@example.com",
            )
            session.add(c)
            customers.append(c)
        session.commit()

    products = session.query(Product).filter_by(company_id=company.id).all()
    if len(products) < len(vendors) * 3:
        print("Creating demo products...")
        for v in vendors:
            for i in range(1, 4):
                p = Product(
                    id=new_id(),
                    company_id=company.id,
                    vendor_id=v.id,
                    name=f"Product {i} by {v.name}",
                    slug=f"prod-{i}-by-{v.slug}",
                    sku=f"SKU-{v.id[:4]}-{i}",
                    regular_price_minor=random.randint(500, 5000) * 100,
                )
                session.add(p)
                products.append(p)
        session.commit()
        products = session.query(Product).filter_by(company_id=company.id).all()

    seed_demo_vendor_access(session, company, vendors, products)
    demo_actor = (
        session.query(User)
        .filter_by(company_id=company.id, username="admin")
        .first()
    )
    if demo_actor is None:
        demo_actor = (
            session.query(User)
            .join(VendorUser, VendorUser.user_id == User.id)
            .filter(VendorUser.company_id == company.id)
            .order_by(VendorUser.created_at, VendorUser.id)
            .first()
        )
    if demo_actor is None:
        raise RuntimeError("A demo vendor user is required to seed inventory and finance data.")
    seed_demo_vendor_inventory(session, company, vendors, products, warehouse, demo_actor.id)
    seed_demo_vendor_ledger(session, company, vendors, demo_actor.id)

    existing_orders = session.query(Order.id).filter_by(company_id=company.id).count()
    if existing_orders:
        print(
            "Skipping order and settlement generation because "
            f"{existing_orders} orders already exist."
        )
        session.close()
        print("Demo data generation complete!")
        return

    print(f"Generating data for 1 month for {len(vendors)} vendors...")

    end_date = datetime.now(UTC)
    start_date = end_date - timedelta(days=30)

    current_date = start_date
    orders_created = 0

    while current_date <= end_date:
        num_orders_today = random.randint(1, 5)
        for _ in range(num_orders_today):
            customer = random.choice(customers)
            order_id = new_id()

            order = Order(
                id=order_id,
                company_id=company.id,
                customer_id=customer.id,
                order_number=f"ORD-{current_date.strftime('%Y%m%d')}-{random.randint(1000, 9999)}",
                status="completed",
                payment_status="paid",
                created_at=current_date,
                updated_at=current_date,
            )

            num_items = random.randint(1, 3)
            order_items = random.sample(products, num_items)

            total_minor = 0
            for item in order_items:
                qty = random.randint(1, 3)
                line_total = qty * item.regular_price_minor
                total_minor += line_total

                oi_id = new_id()
                oi = OrderItem(
                    id=oi_id,
                    company_id=company.id,
                    order_id=order_id,
                    product_id=item.id,
                    vendor_id=item.vendor_id,
                    name=item.name,
                    quantity=qty,
                    unit_price_minor=item.regular_price_minor,
                    line_total_minor=line_total,
                    created_at=current_date,
                    updated_at=current_date,
                )
                session.add(oi)

                if item.vendor_id:
                    commission_bps = 1000  # 10%
                    commission_minor = int((line_total * commission_bps) / 10000)
                    payable_minor = line_total - commission_minor

                    voi = VendorOrderItem(
                        id=new_id(),
                        company_id=company.id,
                        vendor_id=item.vendor_id,
                        order_id=order_id,
                        order_item_id=oi_id,
                        product_id=item.id,
                        name=item.name,
                        quantity=qty,
                        unit_price_minor=item.regular_price_minor,
                        line_total_minor=line_total,
                        commission_bps=commission_bps,
                        commission_minor=commission_minor,
                        payable_minor=payable_minor,
                        status="paid",
                        created_at=current_date,
                        updated_at=current_date,
                    )
                    session.add(voi)

                sm = StockMovement(
                    id=new_id(),
                    company_id=company.id,
                    warehouse_id=warehouse.id,
                    product_id=item.id,
                    movement_type="sale",
                    quantity_delta=-qty,
                    reference_type="order",
                    reference_id=order_id,
                    occurred_at=current_date,
                    created_at=current_date,
                    updated_at=current_date,
                )
                session.add(sm)

            order.subtotal_minor = total_minor
            order.total_minor = total_minor
            order.paid_minor = total_minor
            session.add(order)
            orders_created += 1

        current_date += timedelta(days=1)

    session.commit()
    print(f"Created {orders_created} orders over 30 days.")

    # Create settlements (weekly)
    print("Generating vendor settlements...")
    for v in vendors:
        settlement_start = start_date
        while settlement_start < end_date:
            settlement_end = settlement_start + timedelta(days=7)

            vois = session.query(VendorOrderItem).filter(
                VendorOrderItem.vendor_id == v.id,
                VendorOrderItem.created_at >= settlement_start,
                VendorOrderItem.created_at < settlement_end,
                VendorOrderItem.settlement_id.is_(None),
            ).all()

            if vois:
                s_id = new_id()
                gross = sum(i.line_total_minor for i in vois)
                comm = sum(i.commission_minor for i in vois)
                payable = sum(i.payable_minor for i in vois)

                settlement = VendorSettlement(
                    id=s_id,
                    company_id=company.id,
                    vendor_id=v.id,
                    settlement_number=f"SET-{v.id[:4]}-{settlement_start.strftime('%Y%m%d')}",
                    period_start_at=settlement_start,
                    period_end_at=settlement_end,
                    status="paid",
                    gross_minor=gross,
                    commission_minor=comm,
                    payable_minor=payable,
                    paid_minor=payable,
                    paid_at=settlement_end,
                    created_at=settlement_end,
                    updated_at=settlement_end,
                )
                session.add(settlement)
                for i in vois:
                    i.settlement_id = s_id

            settlement_start = settlement_end

    session.commit()
    session.close()
    print("Demo data generation complete!")


if __name__ == "__main__":
    run()
