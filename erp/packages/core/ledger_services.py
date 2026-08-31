from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from erp.packages.core.config import get_settings
from erp.packages.core.db.models import (
    Account,
    AuditLog,
    Expense,
    JournalEntry,
    JournalLine,
    LedgerAccount,
    LedgerJournal,
    LedgerLine,
    LedgerPeriod,
    Order,
    Payment,
    Product,
    ProductVariant,
    Vendor,
    VendorInventoryBalance,
    VendorInventoryMovement,
    VendorLedgerEntry,
    VendorOrderItem,
    VendorProduct,
    VendorSettlement,
    Warehouse,
    new_uuid,
)
from erp.packages.core.schemas import (
    LedgerJournalCreate,
    LedgerLineCreate,
    LedgerPeriodCreate,
    VendorInventoryMovementCreate,
)
from erp.packages.core.services import ServiceError, record_audit, to_utc, utcnow

DEFAULT_LEDGER_ACCOUNTS: list[tuple[str, str, str]] = [
    ("1000", "Payment Clearing", "asset"),
    ("1010", "Bank", "asset"),
    ("1020", "Rider Cash in Hand", "asset"),
    ("1200", "Inventory", "asset"),
    ("2000", "Vendor Payable", "liability"),
    ("2100", "Commission Payable", "liability"),
    ("2200", "Inventory Clearing", "liability"),
    ("2400", "Rider Earnings Payable", "liability"),
    ("3000", "Commission Revenue", "income"),
    ("3999", "Migration Clearing", "equity"),
    ("4000", "Sales Revenue", "income"),
    ("5000", "Cost of Goods Sold", "expense"),
    ("5100", "Commission Expense", "expense"),
    ("5200", "Rider Delivery Expense", "expense"),
    ("5300", "Refunds and Returns", "expense"),
]
ACCOUNT_TYPES = {"asset", "liability", "equity", "income", "expense", "contra"}
OWNERSHIP_TYPES = {"company_owned", "vendor_owned", "consignment"}
PERIOD_STATUSES = {"open", "locked", "closed"}


def require_company_id(company_id: str | None) -> str:
    if not company_id:
        raise ServiceError(403, "A company-scoped user is required.")
    return company_id


def ensure_default_ledger_accounts(db: Session, company_id: str) -> dict[str, LedgerAccount]:
    legacy_rows = list(db.scalars(select(Account).where(Account.company_id == company_id)).all())
    legacy_by_code = {row.code: row for row in legacy_rows}
    for code, name, account_type in DEFAULT_LEDGER_ACCOUNTS:
        if code not in legacy_by_code:
            legacy = Account(
                company_id=company_id,
                code=code,
                name=name,
                account_type=account_type,
                metadata_json={"projection_owner": "ledger"},
            )
            db.add(legacy)
            db.flush()
            legacy_by_code[code] = legacy

    rows = list(
        db.scalars(select(LedgerAccount).where(LedgerAccount.company_id == company_id)).all()
    )
    by_code = {row.code: row for row in rows}
    # Mirror legacy accounts created during the compatibility window.
    for legacy in legacy_by_code.values():
        if legacy.code not in by_code:
            account_type = legacy.account_type if legacy.account_type in ACCOUNT_TYPES else "contra"
            row = LedgerAccount(
                company_id=company_id,
                code=legacy.code,
                name=legacy.name,
                account_type=account_type,
                is_active=legacy.is_active,
                currency=get_settings().base_currency,
                legacy_account_id=legacy.id,
                metadata_json={"projection": "legacy_account"},
            )
            db.add(row)
            by_code[row.code] = row
    db.flush()
    return by_code


def list_accounts(db: Session, company_id: str | None) -> list[LedgerAccount]:
    scoped = require_company_id(company_id)
    ensure_default_ledger_accounts(db, scoped)
    return list(
        db.scalars(
            select(LedgerAccount)
            .where(LedgerAccount.company_id == scoped)
            .order_by(LedgerAccount.code)
        ).all()
    )


def ensure_period_for_date(db: Session, company_id: str, posted_at: datetime) -> LedgerPeriod:
    normalized = to_utc(posted_at) or utcnow()
    period = db.scalar(
        select(LedgerPeriod).where(
            LedgerPeriod.company_id == company_id,
            LedgerPeriod.starts_at <= normalized,
            LedgerPeriod.ends_at >= normalized,
        )
    )
    if period is None:
        starts = datetime(normalized.year, 1, 1, tzinfo=UTC)
        ends = datetime(normalized.year, 12, 31, 23, 59, 59, 999999, tzinfo=UTC)
        period = LedgerPeriod(
            company_id=company_id,
            name=str(normalized.year),
            starts_at=starts,
            ends_at=ends,
            status="open",
            metadata_json={"created_automatically": True},
        )
        db.add(period)
        db.flush()
    if period.status != "open":
        raise ServiceError(409, f"Ledger period is {period.status}.")
    return period


def create_period(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    payload: LedgerPeriodCreate,
) -> LedgerPeriod:
    scoped = require_company_id(company_id)
    starts = to_utc(payload.starts_at)
    ends = to_utc(payload.ends_at)
    if starts is None or ends is None or ends <= starts:
        raise ServiceError(422, "Ledger period end must be after its start.")
    overlap = db.scalar(
        select(LedgerPeriod.id).where(
            LedgerPeriod.company_id == scoped,
            LedgerPeriod.starts_at <= ends,
            LedgerPeriod.ends_at >= starts,
        )
    )
    if overlap:
        raise ServiceError(409, "Ledger period overlaps an existing period.")
    period = LedgerPeriod(
        company_id=scoped,
        name=payload.name,
        starts_at=starts,
        ends_at=ends,
        status="open",
    )
    db.add(period)
    db.flush()
    record_audit(
        db,
        action="ledger.period_created",
        company_id=scoped,
        user_id=user_id,
        entity_type="ledger_period",
        entity_id=period.id,
    )
    return period


def set_period_status(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    period_id: str,
    status: str,
    reason: str,
) -> LedgerPeriod:
    scoped = require_company_id(company_id)
    if status not in PERIOD_STATUSES:
        raise ServiceError(422, "Unsupported ledger period status.")
    period = db.scalar(
        select(LedgerPeriod).where(LedgerPeriod.company_id == scoped, LedgerPeriod.id == period_id)
    )
    if period is None:
        raise ServiceError(404, "Ledger period not found.")
    if period.status == "closed" and status != "closed":
        raise ServiceError(409, "A closed period cannot be reopened through the API.")
    period.status = status
    period.locked_at = utcnow() if status in {"locked", "closed"} else None
    if status == "closed":
        period.closed_at = utcnow()
        period.closed_by_id = user_id
    record_audit(
        db,
        action=f"ledger.period_{status}",
        company_id=scoped,
        user_id=user_id,
        entity_type="ledger_period",
        entity_id=period.id,
        metadata={"reason": reason},
    )
    db.flush()
    return period


def validate_lines(
    db: Session,
    company_id: str,
    lines: Iterable[LedgerLineCreate],
) -> tuple[int, int]:
    debit_total = 0
    credit_total = 0
    count = 0
    for line in lines:
        count += 1
        if (line.debit_minor > 0) == (line.credit_minor > 0):
            raise ServiceError(422, "Each ledger line requires exactly one debit or credit.")
        account = db.scalar(
            select(LedgerAccount).where(
                LedgerAccount.company_id == company_id,
                LedgerAccount.id == line.account_id,
                LedgerAccount.is_active.is_(True),
            )
        )
        if account is None:
            raise ServiceError(422, "Ledger account is inactive or outside the company.")
        if line.vendor_id and not db.scalar(
            select(Vendor.id).where(Vendor.company_id == company_id, Vendor.id == line.vendor_id)
        ):
            raise ServiceError(422, "Vendor is outside the company.")
        debit_total += line.debit_minor
        credit_total += line.credit_minor
    if count < 2 or debit_total <= 0 or debit_total != credit_total:
        raise ServiceError(422, "Ledger journal debits and credits must balance.")
    return debit_total, credit_total


def generate_entry_number(source_type: str) -> str:
    prefix = "MAN" if source_type == "manual_adjustment" else source_type[:4].upper()
    return f"{prefix}-{utcnow():%Y%m%d}-{new_uuid()[:8].upper()}"


def _append_legacy_vendor_projection(
    db: Session,
    journal: LedgerJournal,
    lines: list[LedgerLine],
) -> None:
    accounts = {
        row.id: row
        for row in db.scalars(
            select(LedgerAccount).where(LedgerAccount.company_id == journal.company_id)
        ).all()
    }
    deltas: dict[str, int] = defaultdict(int)
    for line in lines:
        account = accounts[line.account_id]
        if account.code == "2000" and line.vendor_id:
            deltas[line.vendor_id] += line.credit_minor - line.debit_minor
    for vendor_id, amount in deltas.items():
        if not amount:
            continue
        if db.scalar(
            select(VendorLedgerEntry.id).where(
                VendorLedgerEntry.company_id == journal.company_id,
                VendorLedgerEntry.vendor_id == vendor_id,
                VendorLedgerEntry.source_type == journal.source_type,
                VendorLedgerEntry.source_id == journal.source_id,
            )
        ):
            continue
        balance = (
            int(
                db.scalar(
                    select(func.coalesce(func.sum(VendorLedgerEntry.amount_minor), 0)).where(
                        VendorLedgerEntry.company_id == journal.company_id,
                        VendorLedgerEntry.vendor_id == vendor_id,
                    )
                )
                or 0
            )
            + amount
        )
        db.add(
            VendorLedgerEntry(
                company_id=journal.company_id,
                vendor_id=vendor_id,
                entry_type="settlement" if amount < 0 else "sale",
                source_type=journal.source_type,
                source_id=journal.source_id,
                amount_minor=amount,
                balance_minor=balance,
                memo=journal.memo,
                metadata_json={"ledger_journal_id": journal.id},
            )
        )


def project_legacy_journal(
    db: Session,
    journal: LedgerJournal,
    lines: list[LedgerLine],
) -> JournalEntry:
    existing = db.scalar(
        select(JournalEntry).where(
            JournalEntry.company_id == journal.company_id,
            JournalEntry.source_type == journal.source_type,
            JournalEntry.source_id == journal.source_id,
        )
    )
    if existing:
        return existing
    accounts = {
        row.id: row
        for row in db.scalars(
            select(LedgerAccount).where(LedgerAccount.company_id == journal.company_id)
        ).all()
    }
    entry = JournalEntry(
        company_id=journal.company_id,
        entry_number=f"L-{journal.entry_number}"[:80],
        source_type=journal.source_type,
        source_id=journal.source_id,
        memo=journal.memo,
        status="posted",
        posted_at=journal.posted_at,
        created_by_id=journal.created_by_id,
        metadata_json={"ledger_journal_id": journal.id},
    )
    db.add(entry)
    db.flush()
    for line in lines:
        ledger_account = accounts[line.account_id]
        if not ledger_account.legacy_account_id:
            raise ServiceError(409, "Ledger account has no compatibility projection account.")
        db.add(
            JournalLine(
                company_id=journal.company_id,
                journal_entry_id=entry.id,
                account_id=ledger_account.legacy_account_id,
                debit_minor=line.debit_minor,
                credit_minor=line.credit_minor,
                memo=line.memo,
                metadata_json={"ledger_line_id": line.id},
            )
        )
    _append_legacy_vendor_projection(db, journal, lines)
    db.flush()
    return entry


def post_journal(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    payload: LedgerJournalCreate,
    project_legacy: bool = True,
) -> LedgerJournal:
    scoped = require_company_id(company_id)
    ensure_default_ledger_accounts(db, scoped)
    posted_at = to_utc(payload.posted_at) or utcnow()
    ensure_period_for_date(db, scoped, posted_at)
    validate_lines(db, scoped, payload.lines)
    source_id = payload.source_id or new_uuid()
    idempotency_key = payload.idempotency_key or f"{payload.source_type}:{source_id}"
    if db.scalar(
        select(LedgerJournal.id).where(
            LedgerJournal.company_id == scoped,
            LedgerJournal.idempotency_key == idempotency_key,
        )
    ):
        raise ServiceError(409, "A ledger journal already exists for this source event.")
    journal = LedgerJournal(
        company_id=scoped,
        entry_number=generate_entry_number(payload.source_type),
        source_type=payload.source_type,
        source_id=source_id,
        idempotency_key=idempotency_key,
        status="posted",
        posted_at=posted_at,
        created_by_id=user_id,
        memo=payload.memo,
        metadata_json=payload.metadata,
    )
    db.add(journal)
    db.flush()
    rows: list[LedgerLine] = []
    for item in payload.lines:
        row = LedgerLine(
            journal_id=journal.id,
            company_id=scoped,
            account_id=item.account_id,
            vendor_id=item.vendor_id,
            debit_minor=item.debit_minor,
            credit_minor=item.credit_minor,
            currency=item.currency.upper(),
            memo=item.memo,
            metadata_json=item.metadata,
        )
        db.add(row)
        rows.append(row)
    db.flush()
    if project_legacy:
        project_legacy_journal(db, journal, rows)
    record_audit(
        db,
        action="ledger.journal_posted",
        company_id=scoped,
        user_id=user_id,
        entity_type="ledger_journal",
        entity_id=journal.id,
        metadata={"source_type": journal.source_type, "source_id": journal.source_id},
    )
    db.flush()
    return journal


def get_journal(db: Session, company_id: str | None, journal_id: str) -> LedgerJournal:
    scoped = require_company_id(company_id)
    row = db.scalar(
        select(LedgerJournal).where(
            LedgerJournal.company_id == scoped, LedgerJournal.id == journal_id
        )
    )
    if row is None:
        raise ServiceError(404, "Ledger journal not found.")
    return row


def journal_lines(db: Session, journal_id: str) -> list[LedgerLine]:
    return list(
        db.scalars(
            select(LedgerLine).where(LedgerLine.journal_id == journal_id).order_by(LedgerLine.id)
        ).all()
    )


def list_journals(
    db: Session,
    company_id: str | None,
    *,
    vendor_id: str | None = None,
    account_id: str | None = None,
    source_type: str | None = None,
    status: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    offset: int = 0,
    limit: int = 100,
) -> list[LedgerJournal]:
    scoped = require_company_id(company_id)
    query = select(LedgerJournal).where(LedgerJournal.company_id == scoped)
    if vendor_id:
        query = query.where(
            LedgerJournal.id.in_(
                select(LedgerLine.journal_id).where(
                    LedgerLine.company_id == scoped, LedgerLine.vendor_id == vendor_id
                )
            )
        )
    if account_id:
        query = query.where(
            LedgerJournal.id.in_(
                select(LedgerLine.journal_id).where(
                    LedgerLine.company_id == scoped,
                    LedgerLine.account_id == account_id,
                )
            )
        )
    if source_type:
        query = query.where(LedgerJournal.source_type == source_type)
    if status:
        query = query.where(LedgerJournal.status == status)
    if date_from:
        query = query.where(LedgerJournal.posted_at >= date_from)
    if date_to:
        query = query.where(LedgerJournal.posted_at <= date_to)
    return list(
        db.scalars(
            query.order_by(LedgerJournal.posted_at.desc(), LedgerJournal.id.desc())
            .offset(max(0, offset))
            .limit(max(1, min(limit, 500)))
        ).all()
    )


def reverse_journal(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    journal_id: str,
    reason: str,
    idempotency_key: str | None = None,
) -> LedgerJournal:
    original = get_journal(db, company_id, journal_id)
    if original.status != "posted":
        raise ServiceError(409, "Only a posted journal can be reversed.")
    lines = journal_lines(db, original.id)
    reverse = post_journal(
        db,
        company_id=original.company_id,
        user_id=user_id,
        payload=LedgerJournalCreate(
            source_type="reversal",
            source_id=original.id,
            idempotency_key=idempotency_key or f"reversal:{original.id}",
            memo=reason,
            metadata={"reversal_of_id": original.id},
            lines=[
                LedgerLineCreate(
                    account_id=line.account_id,
                    vendor_id=line.vendor_id,
                    debit_minor=line.credit_minor,
                    credit_minor=line.debit_minor,
                    currency=line.currency,
                    memo=f"Reversal: {line.memo or original.memo or original.entry_number}",
                    metadata={"reversal_of_line_id": line.id},
                )
                for line in lines
            ],
        ),
    )
    reverse.reversal_of_id = original.id
    original.status = "reversed"
    record_audit(
        db,
        action="ledger.journal_reversed",
        company_id=original.company_id,
        user_id=user_id,
        entity_type="ledger_journal",
        entity_id=original.id,
        metadata={"reversal_id": reverse.id, "reason": reason},
    )
    db.flush()
    return reverse


def _date_line_query(
    company_id: str,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
):  # type: ignore[no-untyped-def]
    query = (
        select(LedgerLine, LedgerAccount, LedgerJournal)
        .join(LedgerAccount, LedgerAccount.id == LedgerLine.account_id)
        .join(LedgerJournal, LedgerJournal.id == LedgerLine.journal_id)
        .where(
            LedgerLine.company_id == company_id,
            LedgerJournal.status.in_(["posted", "reversed"]),
        )
    )
    if date_from:
        query = query.where(LedgerJournal.posted_at >= date_from)
    if date_to:
        query = query.where(LedgerJournal.posted_at <= date_to)
    return query


def trial_balance(
    db: Session,
    company_id: str | None,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[dict[str, Any]]:
    scoped = require_company_id(company_id)
    ensure_default_ledger_accounts(db, scoped)
    totals: dict[str, dict[str, Any]] = {}
    for line, account, _journal in db.execute(
        _date_line_query(scoped, date_from=date_from, date_to=date_to)
    ).all():
        row = totals.setdefault(
            account.id,
            {
                "account_id": account.id,
                "account_code": account.code,
                "account_name": account.name,
                "account_type": account.account_type,
                "debit_minor": 0,
                "credit_minor": 0,
                "balance_minor": 0,
            },
        )
        row["debit_minor"] += line.debit_minor
        row["credit_minor"] += line.credit_minor
        row["balance_minor"] = row["debit_minor"] - row["credit_minor"]
    return sorted(totals.values(), key=lambda row: row["account_code"])


def financial_statement(
    db: Session,
    company_id: str | None,
    account_types: set[str],
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, Any]:
    rows = [
        row
        for row in trial_balance(db, company_id, date_from=date_from, date_to=date_to)
        if row["account_type"] in account_types
    ]
    for row in rows:
        if row["account_type"] in {"liability", "equity", "income"}:
            row["statement_balance_minor"] = -row["balance_minor"]
        else:
            row["statement_balance_minor"] = row["balance_minor"]
    return {
        "rows": rows,
        "total_minor": sum(row["statement_balance_minor"] for row in rows),
    }


def vendor_payable_minor(db: Session, company_id: str, vendor_id: str) -> int:
    return int(
        db.scalar(
            select(func.coalesce(func.sum(LedgerLine.credit_minor - LedgerLine.debit_minor), 0))
            .join(LedgerAccount, LedgerAccount.id == LedgerLine.account_id)
            .where(
                LedgerLine.company_id == company_id,
                LedgerLine.vendor_id == vendor_id,
                LedgerAccount.code == "2000",
            )
        )
        or 0
    )


def vendor_ledger_rows(
    db: Session,
    company_id: str,
    vendor_id: str,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    offset: int = 0,
    limit: int = 100,
) -> list[dict[str, Any]]:
    payable_account = db.scalar(
        select(LedgerAccount).where(
            LedgerAccount.company_id == company_id, LedgerAccount.code == "2000"
        )
    )
    if payable_account is None:
        return []
    query = (
        select(LedgerLine, LedgerJournal)
        .join(LedgerJournal, LedgerJournal.id == LedgerLine.journal_id)
        .where(
            LedgerLine.company_id == company_id,
            LedgerLine.vendor_id == vendor_id,
            LedgerLine.account_id == payable_account.id,
        )
        .order_by(LedgerJournal.posted_at, LedgerLine.id)
    )
    if date_from:
        query = query.where(LedgerJournal.posted_at >= date_from)
    if date_to:
        query = query.where(LedgerJournal.posted_at <= date_to)
    all_rows = db.execute(query).all()
    balance = 0
    serialized: list[dict[str, Any]] = []
    for line, journal in all_rows:
        balance += line.credit_minor - line.debit_minor
        serialized.append(
            {
                "journal_id": journal.id,
                "entry_number": journal.entry_number,
                "source_type": journal.source_type,
                "source_id": journal.source_id,
                "posted_at": journal.posted_at,
                "memo": journal.memo,
                "debit_minor": line.debit_minor,
                "credit_minor": line.credit_minor,
                "balance_minor": balance,
                "currency": line.currency,
            }
        )
    return serialized[max(0, offset) : max(0, offset) + max(1, min(limit, 500))]


def vendor_overview(db: Session, company_id: str, vendor_id: str) -> dict[str, Any]:
    vendor = db.scalar(
        select(Vendor).where(Vendor.company_id == company_id, Vendor.id == vendor_id)
    )
    if vendor is None:
        raise ServiceError(404, "Vendor not found.")
    item_totals = db.execute(
        select(
            func.count(VendorOrderItem.id),
            func.coalesce(func.sum(VendorOrderItem.line_total_minor), 0),
            func.coalesce(func.sum(VendorOrderItem.commission_minor), 0),
            func.coalesce(func.sum(VendorOrderItem.payable_minor), 0),
        ).where(VendorOrderItem.company_id == company_id, VendorOrderItem.vendor_id == vendor_id)
    ).one()
    settlement_totals = db.execute(
        select(
            func.count(VendorSettlement.id),
            func.coalesce(func.sum(VendorSettlement.paid_minor), 0),
        ).where(
            VendorSettlement.company_id == company_id,
            VendorSettlement.vendor_id == vendor_id,
        )
    ).one()
    stock = db.execute(
        select(
            func.coalesce(func.sum(VendorInventoryBalance.on_hand_quantity), 0),
            func.coalesce(func.sum(VendorInventoryBalance.reserved_quantity), 0),
            func.coalesce(func.sum(VendorInventoryBalance.available_quantity), 0),
        ).where(
            VendorInventoryBalance.company_id == company_id,
            VendorInventoryBalance.vendor_id == vendor_id,
        )
    ).one()
    outstanding = vendor_payable_minor(db, company_id, vendor_id)
    return {
        "vendor_id": vendor.id,
        "vendor_status": vendor.status,
        "order_count": int(item_totals[0] or 0),
        "gross_sales_minor": int(item_totals[1] or 0),
        "commission_minor": int(item_totals[2] or 0),
        "payable_minor": int(item_totals[3] or 0),
        "settlement_count": int(settlement_totals[0] or 0),
        "settled_minor": int(settlement_totals[1] or 0),
        "outstanding_minor": outstanding,
        "stock_on_hand": int(stock[0] or 0),
        "stock_reserved": int(stock[1] or 0),
        "stock_available": int(stock[2] or 0),
    }


def list_vendor_inventory_balances(
    db: Session,
    company_id: str,
    vendor_id: str | None = None,
    *,
    product_id: str | None = None,
    warehouse_id: str | None = None,
) -> list[VendorInventoryBalance]:
    query = select(VendorInventoryBalance).where(VendorInventoryBalance.company_id == company_id)
    if vendor_id:
        query = query.where(VendorInventoryBalance.vendor_id == vendor_id)
    if product_id:
        query = query.where(VendorInventoryBalance.product_id == product_id)
    if warehouse_id:
        query = query.where(VendorInventoryBalance.warehouse_id == warehouse_id)
    return list(
        db.scalars(
            query.order_by(
                VendorInventoryBalance.vendor_id,
                VendorInventoryBalance.product_id,
                VendorInventoryBalance.warehouse_id,
            )
        ).all()
    )


def list_vendor_inventory_movements(
    db: Session,
    company_id: str,
    vendor_id: str | None = None,
    *,
    product_id: str | None = None,
    warehouse_id: str | None = None,
    movement_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    offset: int = 0,
    limit: int = 100,
) -> list[VendorInventoryMovement]:
    query = select(VendorInventoryMovement).where(VendorInventoryMovement.company_id == company_id)
    if vendor_id:
        query = query.where(VendorInventoryMovement.vendor_id == vendor_id)
    if product_id:
        query = query.where(VendorInventoryMovement.product_id == product_id)
    if warehouse_id:
        query = query.where(VendorInventoryMovement.warehouse_id == warehouse_id)
    if movement_type:
        query = query.where(VendorInventoryMovement.movement_type == movement_type)
    if date_from:
        query = query.where(VendorInventoryMovement.occurred_at >= date_from)
    if date_to:
        query = query.where(VendorInventoryMovement.occurred_at <= date_to)
    return list(
        db.scalars(
            query.order_by(
                VendorInventoryMovement.occurred_at.desc(),
                VendorInventoryMovement.id.desc(),
            )
            .offset(max(0, offset))
            .limit(max(1, min(limit, 500)))
        ).all()
    )


def _validate_inventory_scope(
    db: Session,
    company_id: str,
    payload: VendorInventoryMovementCreate,
) -> VendorProduct:
    if payload.ownership_type not in OWNERSHIP_TYPES:
        raise ServiceError(422, "Unsupported inventory ownership type.")
    if not db.scalar(
        select(Vendor.id).where(Vendor.company_id == company_id, Vendor.id == payload.vendor_id)
    ):
        raise ServiceError(404, "Vendor not found.")
    if not db.scalar(
        select(Product.id).where(Product.company_id == company_id, Product.id == payload.product_id)
    ):
        raise ServiceError(404, "Product not found.")
    if not db.scalar(
        select(Warehouse.id).where(
            Warehouse.company_id == company_id,
            Warehouse.id == payload.warehouse_id,
            Warehouse.is_active.is_(True),
        )
    ):
        raise ServiceError(404, "Active warehouse not found.")
    if payload.variant_id and not db.scalar(
        select(ProductVariant.id).where(
            ProductVariant.company_id == company_id,
            ProductVariant.product_id == payload.product_id,
            ProductVariant.id == payload.variant_id,
        )
    ):
        raise ServiceError(404, "Product variant not found.")
    assignment = db.scalar(
        select(VendorProduct).where(
            VendorProduct.company_id == company_id,
            VendorProduct.vendor_id == payload.vendor_id,
            VendorProduct.product_id == payload.product_id,
        )
    )
    if assignment is None:
        raise ServiceError(409, "Product is not assigned to this vendor.")
    if assignment.ownership_type != payload.ownership_type:
        raise ServiceError(409, "Movement ownership does not match the vendor-product policy.")
    return assignment


def record_vendor_inventory_movement(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    payload: VendorInventoryMovementCreate,
) -> VendorInventoryMovement:
    scoped = require_company_id(company_id)
    _validate_inventory_scope(db, scoped, payload)
    duplicate = db.scalar(
        select(VendorInventoryMovement).where(
            VendorInventoryMovement.company_id == scoped,
            VendorInventoryMovement.idempotency_key == payload.idempotency_key,
        )
    )
    if duplicate:
        raise ServiceError(409, "This inventory movement has already been posted.")

    if payload.movement_type == "reservation" and (
        payload.quantity_delta != 0 or payload.reserved_quantity_delta <= 0
    ):
        raise ServiceError(422, "A reservation requires a positive reserved quantity delta only.")
    if payload.movement_type == "reservation_release" and (
        payload.quantity_delta != 0 or payload.reserved_quantity_delta >= 0
    ):
        raise ServiceError(
            422, "A reservation release requires a negative reserved quantity delta only."
        )

    variant_key = payload.variant_id or ""
    balance_query = select(VendorInventoryBalance).where(
        VendorInventoryBalance.company_id == scoped,
        VendorInventoryBalance.vendor_id == payload.vendor_id,
        VendorInventoryBalance.product_id == payload.product_id,
        VendorInventoryBalance.variant_key == variant_key,
        VendorInventoryBalance.warehouse_id == payload.warehouse_id,
    )
    if db.bind and db.bind.dialect.name == "postgresql":
        balance_query = balance_query.with_for_update()
    balance = db.scalar(balance_query)
    if balance is None:
        balance = VendorInventoryBalance(
            company_id=scoped,
            vendor_id=payload.vendor_id,
            product_id=payload.product_id,
            variant_id=payload.variant_id,
            variant_key=variant_key,
            warehouse_id=payload.warehouse_id,
            ownership_type=payload.ownership_type,
            currency=payload.currency.upper(),
        )
        db.add(balance)
        db.flush()

    before = balance.on_hand_quantity
    after = before + payload.quantity_delta
    reserved_after = balance.reserved_quantity + payload.reserved_quantity_delta
    available_after = after - reserved_after
    if reserved_after < 0:
        raise ServiceError(409, "Reserved stock cannot be negative.")
    if not get_settings().allow_negative_vendor_stock and (after < 0 or available_after < 0):
        raise ServiceError(409, "Insufficient vendor stock for this movement.")
    occurred_at = to_utc(payload.occurred_at) or utcnow()
    balance.on_hand_quantity = after
    balance.reserved_quantity = reserved_after
    balance.available_quantity = available_after
    balance.ownership_type = payload.ownership_type
    balance.unit_cost_minor = payload.unit_cost_minor
    balance.currency = payload.currency.upper()
    balance.last_movement_at = occurred_at
    movement = VendorInventoryMovement(
        company_id=scoped,
        vendor_id=payload.vendor_id,
        product_id=payload.product_id,
        variant_id=payload.variant_id,
        warehouse_id=payload.warehouse_id,
        movement_type=payload.movement_type,
        quantity_delta=payload.quantity_delta,
        quantity_before=before,
        quantity_after=after,
        reserved_quantity_delta=payload.reserved_quantity_delta,
        ownership_type=payload.ownership_type,
        unit_cost_minor=payload.unit_cost_minor,
        valuation_minor=(
            abs(payload.quantity_delta) * payload.unit_cost_minor
            if payload.unit_cost_minor is not None
            else None
        ),
        currency=payload.currency.upper(),
        source_type=payload.source_type,
        source_id=payload.source_id,
        idempotency_key=payload.idempotency_key,
        transfer_group_id=payload.transfer_group_id,
        created_by_id=user_id,
        occurred_at=occurred_at,
        reason=payload.reason,
        metadata_json=payload.metadata,
    )
    db.add(movement)
    db.flush()
    if (
        payload.ownership_type == "company_owned"
        and movement.valuation_minor
        and payload.quantity_delta
        and payload.movement_type not in {"transfer_in", "transfer_out"}
    ):
        accounts = ensure_default_ledger_accounts(db, scoped)
        if payload.quantity_delta > 0:
            valuation_lines = [
                LedgerLineCreate(
                    account_id=accounts["1200"].id,
                    debit_minor=movement.valuation_minor,
                    currency=payload.currency,
                ),
                LedgerLineCreate(
                    account_id=accounts["2200"].id,
                    credit_minor=movement.valuation_minor,
                    currency=payload.currency,
                ),
            ]
        else:
            valuation_lines = [
                LedgerLineCreate(
                    account_id=accounts["5000"].id,
                    debit_minor=movement.valuation_minor,
                    currency=payload.currency,
                ),
                LedgerLineCreate(
                    account_id=accounts["1200"].id,
                    credit_minor=movement.valuation_minor,
                    currency=payload.currency,
                ),
            ]
        post_journal(
            db,
            company_id=scoped,
            user_id=user_id,
            payload=LedgerJournalCreate(
                source_type="vendor_inventory_movement",
                source_id=movement.id,
                idempotency_key=f"vendor-inventory:{payload.idempotency_key}",
                memo=f"{payload.movement_type.replace('_', ' ').title()}: {payload.reason}",
                posted_at=occurred_at,
                metadata={
                    "vendor_id": payload.vendor_id,
                    "product_id": payload.product_id,
                    "ownership_type": payload.ownership_type,
                },
                lines=valuation_lines,
            ),
        )
    record_audit(
        db,
        action="vendor_inventory.movement_posted",
        company_id=scoped,
        user_id=user_id,
        entity_type="vendor_inventory_movement",
        entity_id=movement.id,
        metadata={
            "vendor_id": payload.vendor_id,
            "product_id": payload.product_id,
            "quantity_delta": payload.quantity_delta,
            "reserved_quantity_delta": payload.reserved_quantity_delta,
        },
    )
    return movement


def company_overview(db: Session, company_id: str | None) -> dict[str, int]:
    scoped = require_company_id(company_id)
    rows = trial_balance(db, scoped)
    by_type: dict[str, int] = defaultdict(int)
    for row in rows:
        amount = row["balance_minor"]
        if row["account_type"] in {"liability", "equity", "income"}:
            amount = -amount
        by_type[row["account_type"]] += amount
    inventory = db.execute(
        select(
            func.coalesce(func.sum(VendorInventoryBalance.on_hand_quantity), 0),
            func.coalesce(func.sum(VendorInventoryBalance.reserved_quantity), 0),
        ).where(VendorInventoryBalance.company_id == scoped)
    ).one()
    inventory_value = int(
        db.scalar(
            select(
                func.coalesce(
                    func.sum(
                        VendorInventoryBalance.on_hand_quantity
                        * func.coalesce(VendorInventoryBalance.unit_cost_minor, 0)
                    ),
                    0,
                )
            ).where(VendorInventoryBalance.company_id == scoped)
        )
        or 0
    )
    order_totals = db.execute(
        select(
            func.count(Order.id),
            func.coalesce(func.sum(Order.total_minor), 0),
            func.coalesce(func.sum(Order.paid_minor), 0),
        ).where(Order.company_id == scoped)
    ).one()
    settlement_totals = db.execute(
        select(
            func.count(VendorSettlement.id),
            func.coalesce(func.sum(VendorSettlement.payable_minor), 0),
            func.coalesce(func.sum(VendorSettlement.paid_minor), 0),
        ).where(VendorSettlement.company_id == scoped)
    ).one()
    commission_total = int(
        db.scalar(
            select(func.coalesce(func.sum(VendorOrderItem.commission_minor), 0)).where(
                VendorOrderItem.company_id == scoped
            )
        )
        or 0
    )
    cash_balance = sum(
        row["balance_minor"] for row in rows if row["account_code"] in {"1000", "1010"}
    )
    warning_count = len(reconciliation_issues(db, scoped))
    return {
        "assets_minor": by_type["asset"],
        "liabilities_minor": by_type["liability"],
        "equity_minor": by_type["equity"],
        "income_minor": by_type["income"],
        "expenses_minor": by_type["expense"],
        "vendor_payables_minor": sum(
            vendor_payable_minor(db, scoped, row[0])
            for row in db.execute(select(Vendor.id).where(Vendor.company_id == scoped)).all()
        ),
        "inventory_on_hand": int(inventory[0] or 0),
        "inventory_reserved": int(inventory[1] or 0),
        "inventory_value_minor": inventory_value,
        "cash_balance_minor": int(cash_balance),
        "vendor_count": int(
            db.scalar(select(func.count(Vendor.id)).where(Vendor.company_id == scoped)) or 0
        ),
        "order_count": int(order_totals[0] or 0),
        "gross_order_minor": int(order_totals[1] or 0),
        "paid_sales_minor": int(order_totals[2] or 0),
        "commission_minor": commission_total,
        "settlement_count": int(settlement_totals[0] or 0),
        "settlement_payable_minor": int(settlement_totals[1] or 0),
        "settlement_paid_minor": int(settlement_totals[2] or 0),
        "journal_count": int(
            db.scalar(
                select(func.count(LedgerJournal.id)).where(LedgerJournal.company_id == scoped)
            )
            or 0
        ),
        "reconciliation_warnings": warning_count,
    }


def vendor_payables_report(
    db: Session,
    company_id: str | None,
    *,
    as_of: datetime | None = None,
) -> list[dict[str, Any]]:
    scoped = require_company_id(company_id)
    report_at = to_utc(as_of) or utcnow()
    vendors = list(
        db.scalars(select(Vendor).where(Vendor.company_id == scoped).order_by(Vendor.name)).all()
    )
    payable_account = db.scalar(
        select(LedgerAccount).where(
            LedgerAccount.company_id == scoped,
            LedgerAccount.code == "2000",
        )
    )
    rows: list[dict[str, Any]] = []
    for vendor in vendors:
        performance = db.execute(
            select(
                func.count(VendorOrderItem.id),
                func.coalesce(func.sum(VendorOrderItem.line_total_minor), 0),
                func.coalesce(func.sum(VendorOrderItem.commission_minor), 0),
                func.coalesce(func.sum(VendorOrderItem.payable_minor), 0),
            ).where(
                VendorOrderItem.company_id == scoped,
                VendorOrderItem.vendor_id == vendor.id,
            )
        ).one()
        lots: list[list[Any]] = []
        unapplied_debit = 0
        if payable_account is not None:
            lines = db.execute(
                select(LedgerLine, LedgerJournal)
                .join(LedgerJournal, LedgerJournal.id == LedgerLine.journal_id)
                .where(
                    LedgerLine.company_id == scoped,
                    LedgerLine.vendor_id == vendor.id,
                    LedgerLine.account_id == payable_account.id,
                    LedgerJournal.posted_at <= report_at,
                )
                .order_by(LedgerJournal.posted_at, LedgerLine.id)
            ).all()
            for line, journal in lines:
                credit = int(line.credit_minor - line.debit_minor)
                if credit > 0:
                    lots.append([to_utc(journal.posted_at) or report_at, credit])
                    continue
                debit = -credit
                while debit > 0 and lots:
                    consumed = min(debit, int(lots[0][1]))
                    lots[0][1] = int(lots[0][1]) - consumed
                    debit -= consumed
                    if lots[0][1] == 0:
                        lots.pop(0)
                unapplied_debit += debit
        buckets = {
            "current_minor": 0,
            "days_31_60_minor": 0,
            "days_61_90_minor": 0,
            "days_over_90_minor": 0,
        }
        for posted_at, amount in lots:
            age_days = max(0, (report_at - posted_at).days)
            if age_days <= 30:
                buckets["current_minor"] += int(amount)
            elif age_days <= 60:
                buckets["days_31_60_minor"] += int(amount)
            elif age_days <= 90:
                buckets["days_61_90_minor"] += int(amount)
            else:
                buckets["days_over_90_minor"] += int(amount)
        rows.append(
            {
                "vendor_id": vendor.id,
                "vendor_name": vendor.name,
                "status": vendor.status,
                "as_of": report_at,
                "order_count": int(performance[0] or 0),
                "gross_sales_minor": int(performance[1] or 0),
                "commission_minor": int(performance[2] or 0),
                "payable_minor": int(performance[3] or 0),
                "outstanding_minor": sum(buckets.values()) - unapplied_debit,
                "unapplied_debit_minor": unapplied_debit,
                **buckets,
            }
        )
    return sorted(
        rows,
        key=lambda row: (-int(row["gross_sales_minor"]), str(row["vendor_name"])),
    )


def reconciliation_issues(
    db: Session,
    company_id: str | None,
) -> list[dict[str, Any]]:
    scoped = require_company_id(company_id)
    issues: list[dict[str, Any]] = []

    def source_journal(source_type: str, source_id: str) -> LedgerJournal | None:
        return db.scalar(
            select(LedgerJournal).where(
                LedgerJournal.company_id == scoped,
                LedgerJournal.source_type == source_type,
                LedgerJournal.source_id == source_id,
            )
        )

    expected_sources: list[tuple[str, str]] = []
    expected_sources.extend(
        ("payment", row.id)
        for row in db.scalars(
            select(Payment).where(
                Payment.company_id == scoped,
                Payment.status.in_({"paid", "completed", "captured"}),
                Payment.amount_minor > 0,
            )
        ).all()
    )
    paid_expenses = list(
        db.scalars(
            select(Expense).where(
                Expense.company_id == scoped,
                Expense.status == "paid",
                Expense.amount_minor > 0,
            )
        ).all()
    )
    expected_sources.extend(("expense", row.id) for row in paid_expenses)
    paid_settlements = list(
        db.scalars(
            select(VendorSettlement).where(
                VendorSettlement.company_id == scoped,
                VendorSettlement.status == "paid",
            )
        ).all()
    )
    expected_sources.extend(("settlement", row.id) for row in paid_settlements)
    for source_type, source_id in expected_sources:
        if source_journal(source_type, source_id) is None:
            issues.append(
                {
                    "issue_type": "missing_ledger_posting",
                    "severity": "error",
                    "source_id": source_id,
                    "detail": f"{source_type.title()} has no authoritative ledger journal.",
                }
            )

    for settlement in paid_settlements:
        journal = source_journal("settlement", settlement.id)
        if journal is None:
            continue
        actual = int(
            db.scalar(
                select(
                    func.coalesce(func.sum(LedgerLine.debit_minor - LedgerLine.credit_minor), 0)
                )
                .join(LedgerAccount, LedgerAccount.id == LedgerLine.account_id)
                .where(
                    LedgerLine.company_id == scoped,
                    LedgerLine.journal_id == journal.id,
                    LedgerLine.vendor_id == settlement.vendor_id,
                    LedgerAccount.code == "2000",
                )
            )
            or 0
        )
        expected = int(settlement.paid_minor or settlement.payable_minor)
        if actual != expected:
            issues.append(
                {
                    "issue_type": "settlement_ledger_mismatch",
                    "severity": "error",
                    "source_id": settlement.id,
                    "vendor_id": settlement.vendor_id,
                    "expected_minor": expected,
                    "actual_minor": actual,
                    "detail": "Paid settlement does not match its vendor-payable ledger debit.",
                }
            )

    authoritative_journals = list(
        db.scalars(
            select(LedgerJournal).where(
                LedgerJournal.company_id == scoped,
                LedgerJournal.status.in_({"posted", "reversed"}),
                LedgerJournal.source_type != "legacy_vendor_import",
            )
        ).all()
    )
    for journal in authoritative_journals:
        authority_totals = db.execute(
            select(
                func.coalesce(func.sum(LedgerLine.debit_minor), 0),
                func.coalesce(func.sum(LedgerLine.credit_minor), 0),
            ).where(LedgerLine.journal_id == journal.id)
        ).one()
        legacy_entry = db.scalar(
            select(JournalEntry).where(
                JournalEntry.company_id == scoped,
                JournalEntry.source_type == journal.source_type,
                JournalEntry.source_id == journal.source_id,
            )
        )
        if legacy_entry is None:
            issues.append(
                {
                    "issue_type": "compatibility_projection_missing",
                    "severity": "error",
                    "source_id": journal.source_id,
                    "detail": "Authoritative journal has no legacy compatibility projection.",
                }
            )
            continue
        legacy_totals = db.execute(
            select(
                func.coalesce(func.sum(JournalLine.debit_minor), 0),
                func.coalesce(func.sum(JournalLine.credit_minor), 0),
            ).where(JournalLine.journal_entry_id == legacy_entry.id)
        ).one()
        if tuple(map(int, authority_totals)) != tuple(map(int, legacy_totals)):
            issues.append(
                {
                    "issue_type": "compatibility_projection_drift",
                    "severity": "error",
                    "source_id": journal.source_id,
                    "expected_minor": int(authority_totals[0] or 0),
                    "actual_minor": int(legacy_totals[0] or 0),
                    "detail": "Legacy journal totals differ from the authoritative journal.",
                }
            )

    vendors = list(db.scalars(select(Vendor).where(Vendor.company_id == scoped)).all())
    for vendor in vendors:
        legacy = int(
            db.scalar(
                select(func.coalesce(func.sum(VendorLedgerEntry.amount_minor), 0)).where(
                    VendorLedgerEntry.company_id == scoped,
                    VendorLedgerEntry.vendor_id == vendor.id,
                )
            )
            or 0
        )
        authority = vendor_payable_minor(db, scoped, vendor.id)
        if legacy != authority:
            issues.append(
                {
                    "issue_type": "vendor_payable_projection_drift",
                    "severity": "error",
                    "vendor_id": vendor.id,
                    "expected_minor": authority,
                    "actual_minor": legacy,
                    "detail": "Legacy vendor balance differs from the authoritative ledger.",
                }
            )
    balances = list(
        db.scalars(
            select(VendorInventoryBalance).where(VendorInventoryBalance.company_id == scoped)
        ).all()
    )
    balance_keys = {
        (row.vendor_id, row.product_id, row.variant_id, row.warehouse_id) for row in balances
    }
    movement_groups = db.execute(
        select(
            VendorInventoryMovement.vendor_id,
            VendorInventoryMovement.product_id,
            VendorInventoryMovement.variant_id,
            VendorInventoryMovement.warehouse_id,
        )
        .where(VendorInventoryMovement.company_id == scoped)
        .group_by(
            VendorInventoryMovement.vendor_id,
            VendorInventoryMovement.product_id,
            VendorInventoryMovement.variant_id,
            VendorInventoryMovement.warehouse_id,
        )
    ).all()
    for vendor_id, product_id, variant_id, warehouse_id in movement_groups:
        if (vendor_id, product_id, variant_id, warehouse_id) not in balance_keys:
            issues.append(
                {
                    "issue_type": "vendor_stock_projection_missing",
                    "severity": "error",
                    "vendor_id": vendor_id,
                    "detail": "Inventory movements have no current-balance projection.",
                }
            )
    for balance in balances:
        movement_totals = db.execute(
            select(
                func.coalesce(func.sum(VendorInventoryMovement.quantity_delta), 0),
                func.coalesce(func.sum(VendorInventoryMovement.reserved_quantity_delta), 0),
            ).where(
                VendorInventoryMovement.company_id == scoped,
                VendorInventoryMovement.vendor_id == balance.vendor_id,
                VendorInventoryMovement.product_id == balance.product_id,
                (
                    VendorInventoryMovement.variant_id == balance.variant_id
                    if balance.variant_id
                    else VendorInventoryMovement.variant_id.is_(None)
                ),
                VendorInventoryMovement.warehouse_id == balance.warehouse_id,
            )
        ).one()
        expected_on_hand = int(movement_totals[0] or 0)
        expected_reserved = int(movement_totals[1] or 0)
        if (
            balance.on_hand_quantity != expected_on_hand
            or balance.reserved_quantity != expected_reserved
            or balance.available_quantity != expected_on_hand - expected_reserved
        ):
            issues.append(
                {
                    "issue_type": "vendor_stock_projection_drift",
                    "severity": "error",
                    "source_id": balance.id,
                    "vendor_id": balance.vendor_id,
                    "detail": "Vendor inventory balance differs from immutable movements.",
                }
            )
    duplicates = db.execute(
        select(
            LedgerJournal.company_id,
            LedgerJournal.source_type,
            LedgerJournal.source_id,
            func.count(LedgerJournal.id),
        )
        .where(LedgerJournal.company_id == scoped)
        .group_by(LedgerJournal.company_id, LedgerJournal.source_type, LedgerJournal.source_id)
        .having(func.count(LedgerJournal.id) > 1)
    ).all()
    for _company, source_type, source_id, _count in duplicates:
        issues.append(
            {
                "issue_type": "duplicate_source_posting",
                "severity": "error",
                "source_id": source_id,
                "detail": f"Multiple journals exist for {source_type}/{source_id}.",
            }
        )
    return issues


def vendor_audit_rows(
    db: Session,
    company_id: str,
    vendor_id: str,
    *,
    limit: int = 200,
) -> list[AuditLog]:
    return list(
        db.scalars(
            select(AuditLog)
            .where(
                AuditLog.company_id == company_id,
                or_(
                    and_(AuditLog.entity_type == "vendor", AuditLog.entity_id == vendor_id),
                    AuditLog.metadata_json["vendor_id"].as_string() == vendor_id,
                ),
            )
            .order_by(AuditLog.created_at.desc())
            .limit(max(1, min(limit, 500)))
        ).all()
    )
