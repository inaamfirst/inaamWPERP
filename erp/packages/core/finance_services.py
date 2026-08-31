"""COD, rider, and finance-approval workflows.

The authoritative record is the immutable ledger journal.  The small rider
ledger is a fast, user-facing projection of amounts owed to a rider; it never
replaces the journal.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from erp.packages.core.db.models import (
    CODCollection,
    DeliveryAssignment,
    Expense,
    LedgerAccount,
    LedgerJournal,
    LedgerLine,
    Order,
    Payment,
    RiderCashRemittance,
    RiderFinanceProfile,
    RiderLedgerEntry,
    RiderPayout,
    Role,
    User,
    UserRole,
    VendorOrderItem,
)
from erp.packages.core.schemas import (
    CODCollectionCreate,
    CODReconciliationRequest,
    LedgerJournalCreate,
    LedgerLineCreate,
    RiderAdjustmentCreate,
    RiderFinanceProfileUpdate,
    RiderPayoutCreate,
    RiderRemittanceCreate,
    RiderRemittanceReconciliationRequest,
    VendorFinanceDecision,
)
from erp.packages.core.services import ServiceError, record_audit, to_utc, utcnow


def require_company_id(company_id: str | None) -> str:
    if not company_id:
        raise ServiceError(403, "A company-scoped user is required.")
    return company_id


def _rider(db: Session, company_id: str, rider_user_id: str) -> User:
    rider = db.scalar(
        select(User)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(
            User.company_id == company_id,
            User.id == rider_user_id,
            User.is_active.is_(True),
            User.account_status == "active",
            Role.company_id == company_id,
            Role.name == "Rider",
        )
    )
    if rider is None:
        raise ServiceError(404, "Rider not found.")
    return rider


def _order(db: Session, company_id: str, order_id: str) -> Order:
    order = db.scalar(select(Order).where(Order.company_id == company_id, Order.id == order_id))
    if order is None:
        raise ServiceError(404, "Order not found.")
    return order


def _collection_out(db: Session, row: CODCollection) -> dict[str, Any]:
    order = _order(db, row.company_id, row.order_id)
    rider = _rider(db, row.company_id, row.rider_user_id)
    return {
        "id": row.id,
        "company_id": row.company_id,
        "delivery_assignment_id": row.delivery_assignment_id,
        "order_id": row.order_id,
        "order_number": order.order_number,
        "rider_user_id": row.rider_user_id,
        "rider_name": rider.full_name or rider.username,
        "expected_minor": row.expected_minor,
        "collected_minor": row.collected_minor,
        "accepted_minor": row.accepted_minor,
        "currency": row.currency,
        "receipt_reference": row.receipt_reference,
        "proof_reference": row.proof_reference,
        "status": row.status,
        "payment_id": row.payment_id,
        "reconciled_by_id": row.reconciled_by_id,
        "reconciled_at": row.reconciled_at,
        "reconciliation_reason": row.reconciliation_reason,
        "metadata": row.metadata_json,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _remittance_out(db: Session, row: RiderCashRemittance) -> dict[str, Any]:
    rider = _rider(db, row.company_id, row.rider_user_id)
    return {
        "id": row.id,
        "company_id": row.company_id,
        "rider_user_id": row.rider_user_id,
        "rider_name": rider.full_name or rider.username,
        "amount_minor": row.amount_minor,
        "currency": row.currency,
        "reference": row.reference,
        "proof_reference": row.proof_reference,
        "status": row.status,
        "reconciled_by_id": row.reconciled_by_id,
        "reconciled_at": row.reconciled_at,
        "reconciliation_reason": row.reconciliation_reason,
        "journal_id": row.journal_id,
        "metadata": row.metadata_json,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def profile_out(row: RiderFinanceProfile) -> dict[str, Any]:
    return {
        "id": row.id,
        "company_id": row.company_id,
        "rider_user_id": row.rider_user_id,
        "delivery_fee_minor": row.delivery_fee_minor,
        "currency": row.currency,
        "is_active": row.is_active,
        "metadata": row.metadata_json,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def ledger_entry_out(row: RiderLedgerEntry) -> dict[str, Any]:
    return {
        "id": row.id,
        "company_id": row.company_id,
        "rider_user_id": row.rider_user_id,
        "entry_type": row.entry_type,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "amount_minor": row.amount_minor,
        "balance_minor": row.balance_minor,
        "currency": row.currency,
        "memo": row.memo,
        "journal_id": row.journal_id,
        "metadata": row.metadata_json,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def payout_out(row: RiderPayout) -> dict[str, Any]:
    return {
        "id": row.id,
        "company_id": row.company_id,
        "rider_user_id": row.rider_user_id,
        "payout_number": row.payout_number,
        "amount_minor": row.amount_minor,
        "currency": row.currency,
        "payment_reference": row.payment_reference,
        "status": row.status,
        "paid_at": row.paid_at,
        "paid_by_id": row.paid_by_id,
        "journal_id": row.journal_id,
        "metadata": row.metadata_json,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def get_rider_profile(
    db: Session, company_id: str | None, rider_user_id: str
) -> RiderFinanceProfile | None:
    scoped = require_company_id(company_id)
    return db.scalar(
        select(RiderFinanceProfile).where(
            RiderFinanceProfile.company_id == scoped,
            RiderFinanceProfile.rider_user_id == rider_user_id,
        )
    )


def set_rider_profile(
    db: Session,
    *,
    company_id: str | None,
    actor_user_id: str,
    rider_user_id: str,
    payload: RiderFinanceProfileUpdate,
) -> RiderFinanceProfile:
    scoped = require_company_id(company_id)
    _rider(db, scoped, rider_user_id)
    profile = get_rider_profile(db, scoped, rider_user_id)
    if profile is None:
        profile = RiderFinanceProfile(company_id=scoped, rider_user_id=rider_user_id)
        db.add(profile)
    profile.delivery_fee_minor = payload.delivery_fee_minor
    profile.currency = payload.currency.upper()
    profile.is_active = payload.is_active
    profile.metadata_json = payload.metadata
    db.flush()
    record_audit(
        db,
        action="finance.rider_fee_configured",
        company_id=scoped,
        user_id=actor_user_id,
        entity_type="rider_finance_profile",
        entity_id=profile.id,
        metadata={"rider_user_id": rider_user_id, "delivery_fee_minor": profile.delivery_fee_minor},
    )
    return profile


def list_rider_profiles(db: Session, company_id: str | None) -> list[RiderFinanceProfile]:
    scoped = require_company_id(company_id)
    return list(
        db.scalars(
            select(RiderFinanceProfile)
            .where(RiderFinanceProfile.company_id == scoped)
            .order_by(RiderFinanceProfile.created_at.desc())
        ).all()
    )


def submit_cod_collection(
    db: Session,
    *,
    company_id: str | None,
    rider_user_id: str,
    payload: CODCollectionCreate,
) -> CODCollection:
    scoped = require_company_id(company_id)
    existing = db.scalar(
        select(CODCollection).where(
            CODCollection.company_id == scoped,
            CODCollection.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is not None:
        return existing
    assignment = db.scalar(
        select(DeliveryAssignment).where(
            DeliveryAssignment.company_id == scoped,
            DeliveryAssignment.id == payload.delivery_assignment_id,
            DeliveryAssignment.rider_user_id == rider_user_id,
        )
    )
    if assignment is None:
        raise ServiceError(404, "Delivery assignment not found.")
    if assignment.status != "delivered":
        raise ServiceError(409, "COD can only be submitted for a delivered assignment.")
    order = _order(db, scoped, assignment.order_id)
    expected = max(0, order.total_minor - order.paid_minor)
    if expected <= 0:
        raise ServiceError(409, "This order has no outstanding amount to collect.")
    duplicate = db.scalar(
        select(CODCollection.id).where(
            CODCollection.company_id == scoped,
            CODCollection.delivery_assignment_id == assignment.id,
        )
    )
    if duplicate:
        raise ServiceError(409, "COD has already been submitted for this delivery.")
    collection = CODCollection(
        company_id=scoped,
        delivery_assignment_id=assignment.id,
        order_id=order.id,
        rider_user_id=rider_user_id,
        expected_minor=expected,
        collected_minor=payload.collected_minor,
        currency=order.currency,
        receipt_reference=payload.receipt_reference.strip(),
        proof_reference=payload.proof_reference.strip(),
        status="submitted",
        idempotency_key=payload.idempotency_key,
        metadata_json=payload.metadata,
    )
    db.add(collection)
    db.flush()
    record_audit(
        db,
        action="finance.cod_submitted",
        company_id=scoped,
        user_id=rider_user_id,
        entity_type="cod_collection",
        entity_id=collection.id,
        metadata={"order_id": order.id, "collected_minor": collection.collected_minor},
    )
    return collection


def _collection(db: Session, company_id: str, collection_id: str) -> CODCollection:
    row = db.scalar(
        select(CODCollection).where(
            CODCollection.company_id == company_id, CODCollection.id == collection_id
        )
    )
    if row is None:
        raise ServiceError(404, "COD collection not found.")
    return row


def reconcile_cod_collection(
    db: Session,
    *,
    company_id: str | None,
    actor_user_id: str,
    collection_id: str,
    payload: CODReconciliationRequest,
) -> CODCollection:
    scoped = require_company_id(company_id)
    collection = _collection(db, scoped, collection_id)
    if collection.status != "submitted":
        raise ServiceError(409, "Only a submitted COD collection can be reconciled.")
    if not payload.accepted:
        if not (payload.reason or "").strip():
            raise ServiceError(422, "A reason is required when rejecting COD.")
        collection.status = "rejected"
        collection.reconciliation_reason = payload.reason.strip()
        collection.reconciled_by_id = actor_user_id
        collection.reconciled_at = utcnow()
        db.flush()
        record_audit(
            db,
            action="finance.cod_rejected",
            company_id=scoped,
            user_id=actor_user_id,
            entity_type="cod_collection",
            entity_id=collection.id,
            metadata={"reason": collection.reconciliation_reason},
        )
        return collection

    accepted_minor = payload.accepted_minor or collection.collected_minor
    order = _order(db, scoped, collection.order_id)
    outstanding = max(0, order.total_minor - order.paid_minor)
    if accepted_minor > outstanding:
        raise ServiceError(422, "Accepted COD cannot exceed the order's outstanding balance.")
    if accepted_minor != collection.collected_minor and not (payload.reason or "").strip():
        raise ServiceError(422, "A reason is required for a COD shortage or overage.")

    from erp.packages.core.order_services import record_payment
    from erp.packages.core.schemas import PaymentCreate

    payment = record_payment(
        db,
        company_id=scoped,
        user_id=actor_user_id,
        order_id=order.id,
        payload=PaymentCreate(
            amount_minor=accepted_minor,
            currency=order.currency,
            method="cod",
            status="paid",
            reference=collection.receipt_reference,
            metadata={
                "cod_collection_id": collection.id,
                "rider_user_id": collection.rider_user_id,
                "proof_reference": collection.proof_reference,
            },
        ),
    )
    collection.accepted_minor = accepted_minor
    collection.payment_id = payment.id
    collection.status = "reconciled"
    collection.reconciliation_reason = (payload.reason or "").strip() or None
    collection.reconciled_by_id = actor_user_id
    collection.reconciled_at = utcnow()
    post_rider_earning_for_collection(
        db, company_id=scoped, actor_user_id=actor_user_id, collection=collection
    )
    refresh_vendor_finance_eligibility(db, company_id=scoped, order_id=order.id)
    db.flush()
    record_audit(
        db,
        action="finance.cod_reconciled",
        company_id=scoped,
        user_id=actor_user_id,
        entity_type="cod_collection",
        entity_id=collection.id,
        metadata={"payment_id": payment.id, "accepted_minor": accepted_minor},
    )
    return collection


def refresh_vendor_finance_eligibility(
    db: Session,
    *,
    company_id: str,
    order_id: str,
) -> list[VendorOrderItem]:
    order = _order(db, company_id, order_id)
    delivered = bool(
        db.scalar(
            select(DeliveryAssignment.id).where(
                DeliveryAssignment.company_id == company_id,
                DeliveryAssignment.order_id == order.id,
                DeliveryAssignment.status == "delivered",
            )
        )
    )
    eligible = (
        delivered
        and order.paid_minor >= order.total_minor
        and order.status
        not in {
            "cancelled",
            "returned",
            "refunded",
        }
    )
    rows = list(
        db.scalars(
            select(VendorOrderItem).where(
                VendorOrderItem.company_id == company_id,
                VendorOrderItem.order_id == order.id,
                VendorOrderItem.finance_status == "pending",
            )
        ).all()
    )
    if eligible:
        for row in rows:
            row.finance_status = "eligible"
    db.flush()
    return rows


def _post_rider_journal(
    db: Session,
    *,
    company_id: str,
    actor_user_id: str,
    source_type: str,
    source_id: str,
    idempotency_key: str,
    rider_user_id: str,
    amount_minor: int,
    currency: str,
    memo: str,
) -> LedgerJournal:
    from erp.packages.core.ledger_services import ensure_default_ledger_accounts, post_journal

    accounts = ensure_default_ledger_accounts(db, company_id)
    if amount_minor > 0:
        lines = [
            LedgerLineCreate(
                account_id=accounts["5200"].id, debit_minor=amount_minor, currency=currency
            ),
            LedgerLineCreate(
                account_id=accounts["2400"].id, credit_minor=amount_minor, currency=currency
            ),
        ]
    else:
        amount = abs(amount_minor)
        lines = [
            LedgerLineCreate(account_id=accounts["2400"].id, debit_minor=amount, currency=currency),
            LedgerLineCreate(
                account_id=accounts["5200"].id, credit_minor=amount, currency=currency
            ),
        ]
    return post_journal(
        db,
        company_id=company_id,
        user_id=actor_user_id,
        payload=LedgerJournalCreate(
            source_type=source_type,
            source_id=source_id,
            idempotency_key=idempotency_key,
            memo=memo,
            metadata={"rider_user_id": rider_user_id},
            lines=lines,
        ),
        project_legacy=False,
    )


def rider_balance_minor(db: Session, company_id: str, rider_user_id: str) -> int:
    return int(
        db.scalar(
            select(func.coalesce(func.sum(RiderLedgerEntry.amount_minor), 0)).where(
                RiderLedgerEntry.company_id == company_id,
                RiderLedgerEntry.rider_user_id == rider_user_id,
            )
        )
        or 0
    )


def append_rider_ledger_entry(
    db: Session,
    *,
    company_id: str,
    rider_user_id: str,
    entry_type: str,
    source_type: str,
    source_id: str,
    amount_minor: int,
    currency: str,
    memo: str,
    journal_id: str | None,
    metadata: dict[str, Any] | None = None,
) -> RiderLedgerEntry:
    existing = db.scalar(
        select(RiderLedgerEntry).where(
            RiderLedgerEntry.company_id == company_id,
            RiderLedgerEntry.rider_user_id == rider_user_id,
            RiderLedgerEntry.source_type == source_type,
            RiderLedgerEntry.source_id == source_id,
        )
    )
    if existing is not None:
        return existing
    row = RiderLedgerEntry(
        company_id=company_id,
        rider_user_id=rider_user_id,
        entry_type=entry_type,
        source_type=source_type,
        source_id=source_id,
        amount_minor=amount_minor,
        balance_minor=rider_balance_minor(db, company_id, rider_user_id) + amount_minor,
        currency=currency,
        memo=memo,
        journal_id=journal_id,
        metadata_json=metadata or {},
    )
    db.add(row)
    db.flush()
    return row


def post_rider_earning_for_collection(
    db: Session,
    *,
    company_id: str,
    actor_user_id: str,
    collection: CODCollection,
) -> RiderLedgerEntry | None:
    profile = get_rider_profile(db, company_id, collection.rider_user_id)
    if profile is None or not profile.is_active or profile.delivery_fee_minor <= 0:
        return None
    existing = db.scalar(
        select(RiderLedgerEntry).where(
            RiderLedgerEntry.company_id == company_id,
            RiderLedgerEntry.rider_user_id == collection.rider_user_id,
            RiderLedgerEntry.source_type == "cod_collection",
            RiderLedgerEntry.source_id == collection.id,
        )
    )
    if existing is not None:
        return existing
    journal = _post_rider_journal(
        db,
        company_id=company_id,
        actor_user_id=actor_user_id,
        source_type="rider_earning",
        source_id=collection.id,
        idempotency_key=f"rider-earning:{collection.id}",
        rider_user_id=collection.rider_user_id,
        amount_minor=profile.delivery_fee_minor,
        currency=collection.currency,
        memo=f"Delivery earning for COD collection {collection.receipt_reference}",
    )
    return append_rider_ledger_entry(
        db,
        company_id=company_id,
        rider_user_id=collection.rider_user_id,
        entry_type="earning",
        source_type="cod_collection",
        source_id=collection.id,
        amount_minor=profile.delivery_fee_minor,
        currency=collection.currency,
        memo=f"Delivery earning for {collection.receipt_reference}",
        journal_id=journal.id,
        metadata={"delivery_assignment_id": collection.delivery_assignment_id},
    )


def submit_remittance(
    db: Session,
    *,
    company_id: str | None,
    rider_user_id: str,
    payload: RiderRemittanceCreate,
) -> RiderCashRemittance:
    scoped = require_company_id(company_id)
    existing = db.scalar(
        select(RiderCashRemittance).where(
            RiderCashRemittance.company_id == scoped,
            RiderCashRemittance.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is not None:
        return existing
    _rider(db, scoped, rider_user_id)
    row = RiderCashRemittance(
        company_id=scoped,
        rider_user_id=rider_user_id,
        amount_minor=payload.amount_minor,
        currency="PKR",
        reference=payload.reference.strip(),
        proof_reference=payload.proof_reference.strip(),
        idempotency_key=payload.idempotency_key,
        metadata_json=payload.metadata,
    )
    db.add(row)
    db.flush()
    record_audit(
        db,
        action="finance.rider_remittance_submitted",
        company_id=scoped,
        user_id=rider_user_id,
        entity_type="rider_cash_remittance",
        entity_id=row.id,
        metadata={"amount_minor": row.amount_minor},
    )
    return row


def rider_cash_in_hand_minor(db: Session, company_id: str, rider_user_id: str | None = None) -> int:
    collected_query = select(func.coalesce(func.sum(CODCollection.accepted_minor), 0)).where(
        CODCollection.company_id == company_id,
        CODCollection.status == "reconciled",
    )
    remitted_query = select(func.coalesce(func.sum(RiderCashRemittance.amount_minor), 0)).where(
        RiderCashRemittance.company_id == company_id,
        RiderCashRemittance.status == "reconciled",
    )
    if rider_user_id:
        collected_query = collected_query.where(CODCollection.rider_user_id == rider_user_id)
        remitted_query = remitted_query.where(RiderCashRemittance.rider_user_id == rider_user_id)
    return int(db.scalar(collected_query) or 0) - int(db.scalar(remitted_query) or 0)


def reconcile_remittance(
    db: Session,
    *,
    company_id: str | None,
    actor_user_id: str,
    remittance_id: str,
    payload: RiderRemittanceReconciliationRequest,
) -> RiderCashRemittance:
    scoped = require_company_id(company_id)
    row = db.scalar(
        select(RiderCashRemittance).where(
            RiderCashRemittance.company_id == scoped, RiderCashRemittance.id == remittance_id
        )
    )
    if row is None:
        raise ServiceError(404, "Rider remittance not found.")
    if row.status != "submitted":
        raise ServiceError(409, "Only a submitted remittance can be reconciled.")
    if not payload.accepted:
        if not (payload.reason or "").strip():
            raise ServiceError(422, "A reason is required when rejecting a remittance.")
        row.status = "rejected"
        row.reconciliation_reason = payload.reason.strip()
    else:
        if row.amount_minor > rider_cash_in_hand_minor(db, scoped, row.rider_user_id):
            raise ServiceError(422, "Remittance cannot exceed the rider's reconciled cash in hand.")
        from erp.packages.core.ledger_services import ensure_default_ledger_accounts, post_journal

        accounts = ensure_default_ledger_accounts(db, scoped)
        journal = post_journal(
            db,
            company_id=scoped,
            user_id=actor_user_id,
            payload=LedgerJournalCreate(
                source_type="rider_remittance",
                source_id=row.id,
                idempotency_key=f"rider-remittance:{row.id}",
                memo=f"Rider cash remittance {row.reference}",
                metadata={"rider_user_id": row.rider_user_id},
                lines=[
                    LedgerLineCreate(account_id=accounts["1000"].id, debit_minor=row.amount_minor),
                    LedgerLineCreate(account_id=accounts["1020"].id, credit_minor=row.amount_minor),
                ],
            ),
            project_legacy=False,
        )
        row.status = "reconciled"
        row.journal_id = journal.id
        row.reconciliation_reason = (payload.reason or "").strip() or None
    row.reconciled_by_id = actor_user_id
    row.reconciled_at = utcnow()
    db.flush()
    record_audit(
        db,
        action=f"finance.rider_remittance_{row.status}",
        company_id=scoped,
        user_id=actor_user_id,
        entity_type="rider_cash_remittance",
        entity_id=row.id,
        metadata={"amount_minor": row.amount_minor},
    )
    return row


def post_rider_adjustment(
    db: Session,
    *,
    company_id: str | None,
    actor_user_id: str,
    rider_user_id: str,
    payload: RiderAdjustmentCreate,
) -> RiderLedgerEntry:
    scoped = require_company_id(company_id)
    _rider(db, scoped, rider_user_id)
    existing = db.scalar(
        select(RiderLedgerEntry).where(
            RiderLedgerEntry.company_id == scoped,
            RiderLedgerEntry.rider_user_id == rider_user_id,
            RiderLedgerEntry.source_type == "rider_adjustment",
            RiderLedgerEntry.source_id == payload.idempotency_key,
        )
    )
    if existing is not None:
        return existing
    journal = _post_rider_journal(
        db,
        company_id=scoped,
        actor_user_id=actor_user_id,
        source_type="rider_adjustment",
        source_id=payload.idempotency_key,
        idempotency_key=f"rider-adjustment:{payload.idempotency_key}",
        rider_user_id=rider_user_id,
        amount_minor=payload.amount_minor,
        currency="PKR",
        memo=payload.memo,
    )
    row = append_rider_ledger_entry(
        db,
        company_id=scoped,
        rider_user_id=rider_user_id,
        entry_type="bonus" if payload.amount_minor > 0 else "deduction",
        source_type="rider_adjustment",
        source_id=payload.idempotency_key,
        amount_minor=payload.amount_minor,
        currency="PKR",
        memo=payload.memo,
        journal_id=journal.id,
    )
    record_audit(
        db,
        action="finance.rider_adjusted",
        company_id=scoped,
        user_id=actor_user_id,
        entity_type="rider_ledger_entry",
        entity_id=row.id,
        metadata={"rider_user_id": rider_user_id, "amount_minor": payload.amount_minor},
    )
    return row


def create_rider_payout(
    db: Session,
    *,
    company_id: str | None,
    actor_user_id: str,
    rider_user_id: str,
    payload: RiderPayoutCreate,
) -> RiderPayout:
    scoped = require_company_id(company_id)
    _rider(db, scoped, rider_user_id)
    existing = db.scalar(
        select(RiderPayout).where(
            RiderPayout.company_id == scoped,
            RiderPayout.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is not None:
        return existing
    if payload.amount_minor > rider_balance_minor(db, scoped, rider_user_id):
        raise ServiceError(422, "Rider payout cannot exceed the outstanding earnings balance.")
    from erp.packages.core.ledger_services import ensure_default_ledger_accounts, post_journal

    payout = RiderPayout(
        company_id=scoped,
        rider_user_id=rider_user_id,
        payout_number=f"RPY-{utcnow():%Y%m%d}-{payload.idempotency_key[:32].upper()}",
        amount_minor=payload.amount_minor,
        currency="PKR",
        payment_reference=payload.payment_reference.strip(),
        paid_at=utcnow(),
        paid_by_id=actor_user_id,
        idempotency_key=payload.idempotency_key,
        metadata_json=payload.metadata,
    )
    db.add(payout)
    db.flush()
    accounts = ensure_default_ledger_accounts(db, scoped)
    journal = post_journal(
        db,
        company_id=scoped,
        user_id=actor_user_id,
        payload=LedgerJournalCreate(
            source_type="rider_payout",
            source_id=payout.id,
            idempotency_key=f"rider-payout:{payout.id}",
            memo=f"Rider payout {payout.payout_number}",
            metadata={"rider_user_id": rider_user_id},
            lines=[
                LedgerLineCreate(account_id=accounts["2400"].id, debit_minor=payout.amount_minor),
                LedgerLineCreate(account_id=accounts["1010"].id, credit_minor=payout.amount_minor),
            ],
        ),
        project_legacy=False,
    )
    payout.journal_id = journal.id
    append_rider_ledger_entry(
        db,
        company_id=scoped,
        rider_user_id=rider_user_id,
        entry_type="payout",
        source_type="rider_payout",
        source_id=payout.id,
        amount_minor=-payout.amount_minor,
        currency=payout.currency,
        memo=f"Payout {payout.payment_reference}",
        journal_id=journal.id,
    )
    db.flush()
    record_audit(
        db,
        action="finance.rider_paid",
        company_id=scoped,
        user_id=actor_user_id,
        entity_type="rider_payout",
        entity_id=payout.id,
        metadata={"rider_user_id": rider_user_id, "amount_minor": payout.amount_minor},
    )
    return payout


def decide_vendor_item(
    db: Session,
    *,
    company_id: str | None,
    actor_user_id: str,
    vendor_order_item_id: str,
    payload: VendorFinanceDecision,
) -> VendorOrderItem:
    scoped = require_company_id(company_id)
    item = db.scalar(
        select(VendorOrderItem).where(
            VendorOrderItem.company_id == scoped, VendorOrderItem.id == vendor_order_item_id
        )
    )
    if item is None:
        raise ServiceError(404, "Vendor order item not found.")
    if item.finance_status != "eligible":
        raise ServiceError(409, "Only an eligible vendor sale can be approved or rejected.")
    if not payload.approved:
        if not (payload.reason or "").strip():
            raise ServiceError(422, "A reason is required when rejecting a vendor sale.")
        item.finance_status = "rejected"
        item.finance_reason = payload.reason.strip()
    else:
        order = _order(db, scoped, item.order_id)
        from erp.packages.core.ledger_services import ensure_default_ledger_accounts, post_journal

        accounts = ensure_default_ledger_accounts(db, scoped)
        post_journal(
            db,
            company_id=scoped,
            user_id=actor_user_id,
            payload=LedgerJournalCreate(
                source_type="vendor_approval",
                source_id=item.id,
                idempotency_key=f"vendor-approval:{item.id}",
                memo=f"Approved vendor payable for order {order.order_number}",
                metadata={"vendor_order_item_id": item.id, "order_id": order.id},
                lines=[
                    LedgerLineCreate(
                        account_id=accounts["5000"].id,
                        debit_minor=item.payable_minor,
                        currency=order.currency,
                    ),
                    LedgerLineCreate(
                        account_id=accounts["2000"].id,
                        vendor_id=item.vendor_id,
                        credit_minor=item.payable_minor,
                        currency=order.currency,
                    ),
                ],
            ),
            project_legacy=False,
        )
        item.finance_status = "approved"
        item.finance_approved_by_id = actor_user_id
        item.finance_approved_at = utcnow()
        item.finance_reason = (payload.reason or "").strip() or None
    db.flush()
    record_audit(
        db,
        action=f"finance.vendor_sale_{item.finance_status}",
        company_id=scoped,
        user_id=actor_user_id,
        entity_type="vendor_order_item",
        entity_id=item.id,
        metadata={"vendor_id": item.vendor_id, "payable_minor": item.payable_minor},
    )
    return item


def list_collections(
    db: Session,
    company_id: str | None,
    *,
    rider_user_id: str | None = None,
    status: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[CODCollection]:
    scoped = require_company_id(company_id)
    query = select(CODCollection).where(CODCollection.company_id == scoped)
    if rider_user_id:
        query = query.where(CODCollection.rider_user_id == rider_user_id)
    if status:
        query = query.where(CODCollection.status == status)
    start = to_utc(date_from)
    end = to_utc(date_to)
    if start is not None:
        query = query.where(CODCollection.created_at >= start)
    if end is not None:
        query = query.where(CODCollection.created_at <= end)
    return list(db.scalars(query.order_by(CODCollection.created_at.desc())).all())


def list_remittances(
    db: Session,
    company_id: str | None,
    *,
    rider_user_id: str | None = None,
    status: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[RiderCashRemittance]:
    scoped = require_company_id(company_id)
    query = select(RiderCashRemittance).where(RiderCashRemittance.company_id == scoped)
    if rider_user_id:
        query = query.where(RiderCashRemittance.rider_user_id == rider_user_id)
    if status:
        query = query.where(RiderCashRemittance.status == status)
    start = to_utc(date_from)
    end = to_utc(date_to)
    if start is not None:
        query = query.where(RiderCashRemittance.created_at >= start)
    if end is not None:
        query = query.where(RiderCashRemittance.created_at <= end)
    return list(db.scalars(query.order_by(RiderCashRemittance.created_at.desc())).all())


def list_rider_ledger_entries(
    db: Session, company_id: str | None, rider_user_id: str
) -> list[RiderLedgerEntry]:
    scoped = require_company_id(company_id)
    return list(
        db.scalars(
            select(RiderLedgerEntry)
            .where(
                RiderLedgerEntry.company_id == scoped,
                RiderLedgerEntry.rider_user_id == rider_user_id,
            )
            .order_by(RiderLedgerEntry.created_at, RiderLedgerEntry.id)
        ).all()
    )


def list_rider_payouts(
    db: Session, company_id: str | None, rider_user_id: str
) -> list[RiderPayout]:
    scoped = require_company_id(company_id)
    return list(
        db.scalars(
            select(RiderPayout)
            .where(RiderPayout.company_id == scoped, RiderPayout.rider_user_id == rider_user_id)
            .order_by(RiderPayout.paid_at.desc(), RiderPayout.id.desc())
        ).all()
    )


def rider_summary(db: Session, company_id: str | None, rider_user_id: str) -> dict[str, int]:
    scoped = require_company_id(company_id)
    return {
        "cash_in_hand_minor": rider_cash_in_hand_minor(db, scoped, rider_user_id),
        "earnings_payable_minor": rider_balance_minor(db, scoped, rider_user_id),
        "pending_cod_minor": int(
            db.scalar(
                select(func.coalesce(func.sum(CODCollection.collected_minor), 0)).where(
                    CODCollection.company_id == scoped,
                    CODCollection.rider_user_id == rider_user_id,
                    CODCollection.status == "submitted",
                )
            )
            or 0
        ),
    }


def finance_dashboard(
    db: Session,
    company_id: str | None,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, int]:
    scoped = require_company_id(company_id)
    from erp.packages.core import ledger_services

    start = to_utc(date_from)
    end = to_utc(date_to)
    if start is not None and end is not None and start > end:
        raise ServiceError(422, "date_from must be before date_to.")

    def within_period(column: Any) -> list[Any]:
        filters: list[Any] = []
        if start is not None:
            filters.append(column >= start)
        if end is not None:
            filters.append(column <= end)
        return filters

    # Payments move to ``refunded`` when a refund reversal is posted.  Count
    # both states here so the dashboard shows gross collections and refunds as
    # separate, auditable figures rather than silently erasing the sale.
    collected_sales = int(
        db.scalar(
            select(func.coalesce(func.sum(Payment.amount_minor), 0)).where(
                Payment.company_id == scoped,
                Payment.status.in_(["paid", "refunded"]),
                *within_period(Payment.created_at),
            )
        )
        or 0
    )
    pending_cod = int(
        db.scalar(
            select(func.coalesce(func.sum(CODCollection.collected_minor), 0)).where(
                CODCollection.company_id == scoped,
                CODCollection.status == "submitted",
                *within_period(CODCollection.created_at),
            )
        )
        or 0
    )
    approved_vendor = int(
        db.scalar(
            select(func.coalesce(func.sum(VendorOrderItem.payable_minor), 0)).where(
                VendorOrderItem.company_id == scoped,
                VendorOrderItem.finance_status.in_(["approved", "allocated", "paid"]),
                *within_period(VendorOrderItem.created_at),
            )
        )
        or 0
    )
    rider_expense = int(
        db.scalar(
            select(func.coalesce(func.sum(RiderLedgerEntry.amount_minor), 0)).where(
                RiderLedgerEntry.company_id == scoped,
                RiderLedgerEntry.entry_type.in_(["earning", "bonus", "deduction"]),
                *within_period(RiderLedgerEntry.created_at),
            )
        )
        or 0
    )
    business_expense = int(
        db.scalar(
            select(func.coalesce(func.sum(Expense.amount_minor), 0)).where(
                Expense.company_id == scoped,
                Expense.status == "paid",
                *within_period(Expense.created_at),
            )
        )
        or 0
    )
    refunds = int(
        db.scalar(
            select(func.coalesce(func.sum(Payment.amount_minor), 0)).where(
                Payment.company_id == scoped,
                Payment.status == "refunded",
                *within_period(Payment.created_at),
            )
        )
        or 0
    )
    vendor_payables = int(
        db.scalar(
            select(func.coalesce(func.sum(LedgerLine.credit_minor - LedgerLine.debit_minor), 0))
            .join(LedgerAccount, LedgerAccount.id == LedgerLine.account_id)
            .where(
                LedgerLine.company_id == scoped,
                LedgerAccount.code == "2000",
            )
        )
        or 0
    )
    return {
        "collected_sales_minor": collected_sales,
        "pending_cod_minor": pending_cod,
        "rider_cash_in_hand_minor": rider_cash_in_hand_minor(db, scoped),
        "vendor_payables_minor": vendor_payables,
        "approved_vendor_payouts_minor": approved_vendor,
        "rider_earnings_payable_minor": int(
            db.scalar(
                select(func.coalesce(func.sum(RiderLedgerEntry.amount_minor), 0)).where(
                    RiderLedgerEntry.company_id == scoped
                )
            )
            or 0
        ),
        "delivery_expense_minor": rider_expense,
        "expenses_minor": business_expense,
        "refunds_minor": refunds,
        "net_operational_profit_minor": collected_sales
        - approved_vendor
        - rider_expense
        - business_expense
        - refunds,
        "reconciliation_warnings": len(ledger_services.reconciliation_issues(db, scoped)),
    }
