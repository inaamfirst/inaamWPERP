from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from erp.packages.core.catalog_services import create_product
from erp.packages.core.customer_services import create_customer
from erp.packages.core.db.base import Base
from erp.packages.core.db.models import (
    JournalEntry,
    Order,
    ProductVariant,
    VendorLedgerEntry,
    VendorOrderItem,
)
from erp.packages.core.marketplace_services import create_vendor, vendor_order_item_out
from erp.packages.core.order_services import create_order, record_payment
from erp.packages.core.schemas import (
    CustomerCreate,
    FirstUseSetupRequest,
    OrderCreate,
    OrderItemCreate,
    PaymentCreate,
    ProductCreate,
    ProductVariantCreate,
    VendorCreate,
)
from erp.packages.core.services import setup_first_use


def test_vendor_order_capture_and_payment_posting(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'marketplace_accounting.db'}", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )

    with session_factory() as db:
        issued = setup_first_use(
            db,
            FirstUseSetupRequest(
                company_name="Vendor Co",
                username="admin",
                password="admin12345",
                full_name="Admin User",
                email="admin@example.com",
            ),
        )
        db.commit()

        vendor = create_vendor(
            db,
            company_id=issued.user.company_id,
            user_id=issued.user.id,
            payload=VendorCreate(
                name="Vendor One",
                slug="vendor-one",
                status="active",
                default_commission_bps=1000,
            ),
        )

        product = create_product(
            db,
            company_id=issued.user.company_id,
            user_id=issued.user.id,
            payload=ProductCreate(
                name="Vendor Product",
                vendor_id=vendor.id,
                sku="VENDOR-SKU",
                variants=[
                    ProductVariantCreate(
                        sku="VENDOR-SKU-1",
                        price_minor=2500,
                    )
                ],
            ),
        )
        variant = db.scalar(select(ProductVariant).where(ProductVariant.product_id == product.id))
        assert variant is not None

        customer = create_customer(
            db,
            company_id=issued.user.company_id,
            user_id=issued.user.id,
            payload=CustomerCreate(full_name="Test Customer", email="customer@example.com"),
        )

        order = create_order(
            db,
            company_id=issued.user.company_id,
            user_id=issued.user.id,
            payload=OrderCreate(
                customer_id=customer.id,
                currency="PKR",
                items=[
                    OrderItemCreate(
                        product_id=product.id,
                        variant_id=variant.id,
                        quantity=2,
                    )
                ],
            ),
        )
        assert order.total_minor == 5000

        order_item = db.scalar(select(VendorOrderItem).where(VendorOrderItem.order_id == order.id))
        assert order_item is not None
        assert order_item.vendor_id == vendor.id
        assert order_item.commission_minor == 500
        assert order_item.payable_minor == 4500

        payment = record_payment(
            db,
            company_id=issued.user.company_id,
            user_id=issued.user.id,
            order_id=order.id,
            payload=PaymentCreate(
                amount_minor=5000,
                currency="PKR",
                method="cash",
                status="paid",
            ),
        )
        db.commit()

        journal_entry = db.scalar(
            select(JournalEntry).where(
                JournalEntry.company_id == issued.user.company_id,
                JournalEntry.source_type == "payment",
                JournalEntry.source_id == payment.id,
            )
        )
        ledger_entry = db.scalar(
            select(VendorLedgerEntry).where(
                VendorLedgerEntry.company_id == issued.user.company_id,
                VendorLedgerEntry.vendor_id == vendor.id,
                VendorLedgerEntry.source_type == "payment",
                VendorLedgerEntry.source_id == payment.id,
            )
        )
        refreshed_order = db.scalar(select(Order).where(Order.id == order.id))

        assert payment.status == "paid"
        assert refreshed_order is not None
        assert refreshed_order.payment_status == "paid"
        assert journal_entry is not None
        assert journal_entry.source_type == "payment"
        assert ledger_entry is not None
        assert ledger_entry.amount_minor == 4500
        assert ledger_entry.balance_minor == 4500
        vendor_sale = vendor_order_item_out(order_item, db=db)
        assert vendor_sale.order_number == order.order_number
        assert vendor_sale.order_status == order.status
        assert vendor_sale.payment_status == "paid"
