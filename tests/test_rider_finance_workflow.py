from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from erp.packages.core.catalog_services import create_product
from erp.packages.core.customer_services import create_customer
from erp.packages.core.db.base import Base
from erp.packages.core.db.models import (
    LedgerAccount,
    LedgerLine,
    ProductVariant,
    RiderLedgerEntry,
    Role,
    User,
    UserRole,
    VendorOrderItem,
)
from erp.packages.core.delivery_services import change_assignment_status, create_assignment
from erp.packages.core.finance_services import (
    create_rider_payout,
    decide_vendor_item,
    finance_dashboard,
    reconcile_cod_collection,
    reconcile_remittance,
    rider_cash_in_hand_minor,
    rider_summary,
    set_rider_profile,
    submit_cod_collection,
    submit_remittance,
)
from erp.packages.core.marketplace_services import create_vendor, create_vendor_settlement
from erp.packages.core.order_services import change_order_status, create_order
from erp.packages.core.schemas import (
    CODCollectionCreate,
    CODReconciliationRequest,
    CustomerCreate,
    FirstUseSetupRequest,
    OrderCreate,
    OrderItemCreate,
    OrderStatusChange,
    ProductCreate,
    ProductVariantCreate,
    RiderFinanceProfileUpdate,
    RiderPayoutCreate,
    RiderRemittanceCreate,
    RiderRemittanceReconciliationRequest,
    VendorCreate,
    VendorFinanceDecision,
    VendorSettlementCreate,
)
from erp.packages.core.services import setup_first_use


def test_reconciled_cod_approves_vendor_sale_and_clears_rider_balances(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'rider_finance.db'}", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    with session_factory() as db:
        issued = setup_first_use(
            db,
            FirstUseSetupRequest(
                company_name="Rider Finance Co",
                username="admin",
                password="admin12345",
                full_name="Finance Admin",
                email="finance@example.test",
            ),
        )
        company_id = issued.user.company_id
        assert company_id is not None
        rider_role = db.scalar(
            select(Role).where(Role.company_id == company_id, Role.name == "Rider")
        )
        assert rider_role is not None
        rider = User(
            company_id=company_id,
            username="rider-one",
            email="rider@example.test",
            password_hash="unused-in-service-test",
            full_name="Rider One",
            account_status="active",
        )
        db.add(rider)
        db.flush()
        db.add(UserRole(user_id=rider.id, role_id=rider_role.id))

        vendor = create_vendor(
            db,
            company_id=company_id,
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
            company_id=company_id,
            user_id=issued.user.id,
            payload=ProductCreate(
                name="Delivery Product",
                vendor_id=vendor.id,
                sku="DELIVERY-SKU",
                variants=[ProductVariantCreate(sku="DELIVERY-SKU-1", price_minor=5000)],
            ),
        )
        variant = db.scalar(select(ProductVariant).where(ProductVariant.product_id == product.id))
        assert variant is not None
        customer = create_customer(
            db,
            company_id=company_id,
            user_id=issued.user.id,
            payload=CustomerCreate(
                full_name="COD Customer",
                phone="03001234567",
                addresses=[
                    {
                        "label": "Home",
                        "recipient_name": "COD Customer",
                        "phone": "03001234567",
                        "line1": "1 Main Street",
                        "city": "Lahore",
                        "country": "PK",
                        "is_default": True,
                    }
                ],
            ),
        )
        order = create_order(
            db,
            company_id=company_id,
            user_id=issued.user.id,
            payload=OrderCreate(
                customer_id=customer.id,
                items=[OrderItemCreate(product_id=product.id, variant_id=variant.id, quantity=1)],
            ),
        )
        # Delivery assignment is intentionally allowed only after fulfilment
        # reaches ready; setup of that operational state is outside this money
        # workflow test.
        order.status = "ready"
        assignment = create_assignment(
            db,
            company_id=company_id,
            admin_user_id=issued.user.id,
            order_id=order.id,
            rider_user_id=rider.id,
        )
        for status in ("picked_up", "out_for_delivery", "delivered"):
            assignment = change_assignment_status(
                db,
                company_id=company_id,
                rider_user_id=rider.id,
                assignment_id=assignment.id,
                status=status,
            )

        set_rider_profile(
            db,
            company_id=company_id,
            actor_user_id=issued.user.id,
            rider_user_id=rider.id,
            payload=RiderFinanceProfileUpdate(delivery_fee_minor=300),
        )
        collection_payload = CODCollectionCreate(
            delivery_assignment_id=assignment.id,
            collected_minor=5000,
            receipt_reference="COD-1001",
            proof_reference="proof://cod-1001",
            idempotency_key="cod-1001",
        )
        collection = submit_cod_collection(
            db, company_id=company_id, rider_user_id=rider.id, payload=collection_payload
        )
        # A retry is safe and returns the existing submission, rather than
        # creating an extra payment or cash balance.
        assert (
            submit_cod_collection(
                db, company_id=company_id, rider_user_id=rider.id, payload=collection_payload
            ).id
            == collection.id
        )

        collection = reconcile_cod_collection(
            db,
            company_id=company_id,
            actor_user_id=issued.user.id,
            collection_id=collection.id,
            payload=CODReconciliationRequest(accepted=True),
        )
        item = db.scalar(select(VendorOrderItem).where(VendorOrderItem.order_id == order.id))
        assert item is not None
        assert collection.status == "reconciled"
        assert collection.accepted_minor == 5000
        assert order.paid_minor == 5000
        assert item.finance_status == "eligible"
        assert rider_summary(db, company_id, rider.id) == {
            "cash_in_hand_minor": 5000,
            "earnings_payable_minor": 300,
            "pending_cod_minor": 0,
        }

        decide_vendor_item(
            db,
            company_id=company_id,
            actor_user_id=issued.user.id,
            vendor_order_item_id=item.id,
            payload=VendorFinanceDecision(approved=True),
        )
        settlement = create_vendor_settlement(
            db,
            company_id=company_id,
            user_id=issued.user.id,
            payload=VendorSettlementCreate(
                vendor_id=vendor.id,
                payment_reference="VENDOR-BANK-1001",
            ),
        )
        assert settlement.status == "paid"
        assert item.finance_status == "paid"
        assert settlement.payable_minor == 4500

        remittance = submit_remittance(
            db,
            company_id=company_id,
            rider_user_id=rider.id,
            payload=RiderRemittanceCreate(
                amount_minor=5000,
                reference="HANDOVER-1001",
                proof_reference="proof://handover-1001",
                idempotency_key="remittance-1001",
            ),
        )
        reconcile_remittance(
            db,
            company_id=company_id,
            actor_user_id=issued.user.id,
            remittance_id=remittance.id,
            payload=RiderRemittanceReconciliationRequest(accepted=True),
        )
        payout = create_rider_payout(
            db,
            company_id=company_id,
            actor_user_id=issued.user.id,
            rider_user_id=rider.id,
            payload=RiderPayoutCreate(
                amount_minor=300,
                payment_reference="RIDER-BANK-1001",
                idempotency_key="rider-payout-1001",
            ),
        )
        db.flush()

        assert payout.status == "paid"
        assert rider_cash_in_hand_minor(db, company_id, rider.id) == 0
        assert rider_summary(db, company_id, rider.id)["earnings_payable_minor"] == 0
        dashboard = finance_dashboard(db, company_id)
        assert dashboard["collected_sales_minor"] == 5000
        assert dashboard["approved_vendor_payouts_minor"] == 4500
        assert dashboard["delivery_expense_minor"] == 300
        assert dashboard["net_operational_profit_minor"] == 200
        assert (
            db.scalar(
                select(func.count(RiderLedgerEntry.id)).where(
                    RiderLedgerEntry.company_id == company_id,
                    RiderLedgerEntry.rider_user_id == rider.id,
                )
            )
            == 2
        )
        for account_code in ("1020", "2000", "2400"):
            account = db.scalar(
                select(LedgerAccount).where(
                    LedgerAccount.company_id == company_id, LedgerAccount.code == account_code
                )
            )
            assert account is not None
            balance = db.scalar(
                select(
                    func.coalesce(func.sum(LedgerLine.debit_minor - LedgerLine.credit_minor), 0)
                ).where(
                    LedgerLine.company_id == company_id,
                    LedgerLine.account_id == account.id,
                )
            )
            assert balance == 0

        # A refund never rewrites the original journals. It posts matching
        # reversals and a rider deduction, leaving an auditable recovery
        # balance if the rider was already paid.
        order.status = "delivered"
        change_order_status(
            db,
            company_id=company_id,
            user_id=issued.user.id,
            order_id=order.id,
            payload=OrderStatusChange(status="refunded", reason="Customer return"),
        )
        assert item.finance_status == "reversed"
        assert rider_summary(db, company_id, rider.id)["earnings_payable_minor"] == -300
        refunded_dashboard = finance_dashboard(db, company_id)
        assert refunded_dashboard["refunds_minor"] == 5000
        assert refunded_dashboard["net_operational_profit_minor"] == 0

        db.commit()
    engine.dispose()
