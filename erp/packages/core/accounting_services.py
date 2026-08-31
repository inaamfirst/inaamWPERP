from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from erp.packages.core.db.models import (
    Account,
    AccountingPeriod,
    BankAccount,
    CashBook,
    Expense,
    JournalEntry,
    JournalLine,
    LedgerAccount,
    Order,
    Payment,
    VendorLedgerEntry,
    VendorOrderItem,
    VendorSettlement,
    new_uuid,
)
from erp.packages.core.schemas import (
    AccountCreate,
    AccountingPeriodCreate,
    AccountingPeriodOut,
    AccountingPeriodUpdate,
    AccountOut,
    AccountUpdate,
    BankAccountCreate,
    BankAccountOut,
    CashBookCreate,
    CashBookOut,
    ExpenseCreate,
    ExpenseOut,
    JournalEntryCreate,
    JournalEntryOut,
    JournalLineCreate,
    JournalLineOut,
    LedgerJournalCreate,
    LedgerLineCreate,
    VendorLedgerEntryOut,
)
from erp.packages.core.services import ServiceError, record_audit, utcnow

DEFAULT_ACCOUNTS: list[tuple[str, str, str]] = [
    ("1000", "Payment Clearing", "asset"),
    ("1010", "Bank", "asset"),
    ("2000", "Vendor Payable", "liability"),
    ("3000", "Commission Revenue", "income"),
    ("4000", "Sales Revenue", "income"),
]

ACCOUNTING_PERIOD_STATUSES = {"open", "locked", "closed"}
JOURNAL_STATUSES = {"draft", "posted", "void"}
EXPENSE_STATUSES = {"draft", "approved", "paid", "void"}


def require_company_id(company_id: str | None) -> str:
    if not company_id:
        raise ServiceError(403, "A company-scoped user is required.")
    return company_id


def generate_entry_number(prefix: str = "JE") -> str:
    return f"{prefix}-{utcnow():%Y%m%d}-{new_uuid()[:8].upper()}"


def account_out(account: Account) -> AccountOut:
    return AccountOut(
        id=account.id,
        company_id=account.company_id,
        code=account.code,
        name=account.name,
        account_type=account.account_type,
        parent_id=account.parent_id,
        is_active=account.is_active,
        metadata=account.metadata_json,
        created_at=account.created_at,
        updated_at=account.updated_at,
    )


def period_out(period: AccountingPeriod) -> AccountingPeriodOut:
    return AccountingPeriodOut(
        id=period.id,
        company_id=period.company_id,
        name=period.name,
        starts_at=period.starts_at,
        ends_at=period.ends_at,
        status=period.status,
        locked_at=period.locked_at,
        metadata=period.metadata_json,
        created_at=period.created_at,
        updated_at=period.updated_at,
    )


def journal_line_out(line: JournalLine) -> JournalLineOut:
    return JournalLineOut(
        id=line.id,
        company_id=line.company_id,
        journal_entry_id=line.journal_entry_id,
        account_id=line.account_id,
        debit_minor=line.debit_minor,
        credit_minor=line.credit_minor,
        memo=line.memo,
        metadata=line.metadata_json,
    )


def vendor_ledger_entry_out(entry: VendorLedgerEntry) -> VendorLedgerEntryOut:
    return VendorLedgerEntryOut(
        id=entry.id,
        company_id=entry.company_id,
        vendor_id=entry.vendor_id,
        entry_type=entry.entry_type,
        source_type=entry.source_type,
        source_id=entry.source_id,
        amount_minor=entry.amount_minor,
        balance_minor=entry.balance_minor,
        memo=entry.memo,
        metadata=entry.metadata_json,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


def expense_out(expense: Expense) -> ExpenseOut:
    return ExpenseOut(
        id=expense.id,
        company_id=expense.company_id,
        expense_number=expense.expense_number,
        account_id=expense.account_id,
        vendor_id=expense.vendor_id,
        cash_book_id=expense.cash_book_id,
        bank_account_id=expense.bank_account_id,
        amount_minor=expense.amount_minor,
        currency=expense.currency,
        status=expense.status,
        memo=expense.memo,
        incurred_at=expense.incurred_at,
        paid_at=expense.paid_at,
        metadata=expense.metadata_json,
        created_at=expense.created_at,
        updated_at=expense.updated_at,
    )


def cash_book_out(book: CashBook) -> CashBookOut:
    return CashBookOut(
        id=book.id,
        company_id=book.company_id,
        code=book.code,
        name=book.name,
        currency=book.currency,
        opening_balance_minor=book.opening_balance_minor,
        is_active=book.is_active,
        metadata=book.metadata_json,
        created_at=book.created_at,
        updated_at=book.updated_at,
    )


def bank_account_out(account: BankAccount) -> BankAccountOut:
    return BankAccountOut(
        id=account.id,
        company_id=account.company_id,
        code=account.code,
        bank_name=account.bank_name,
        account_name=account.account_name,
        account_number=account.account_number,
        iban=account.iban,
        currency=account.currency,
        opening_balance_minor=account.opening_balance_minor,
        is_active=account.is_active,
        metadata=account.metadata_json,
        created_at=account.created_at,
        updated_at=account.updated_at,
    )


def journal_entry_out(db: Session, entry: JournalEntry) -> JournalEntryOut:
    lines = list(
        db.scalars(
            select(JournalLine)
            .where(JournalLine.journal_entry_id == entry.id)
            .order_by(JournalLine.id)
        ).all()
    )
    return JournalEntryOut(
        id=entry.id,
        company_id=entry.company_id,
        entry_number=entry.entry_number,
        source_type=entry.source_type,
        source_id=entry.source_id,
        memo=entry.memo,
        status=entry.status,
        posted_at=entry.posted_at,
        metadata=entry.metadata_json,
        lines=[journal_line_out(line) for line in lines],
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


def ensure_default_accounts(db: Session, company_id: str) -> dict[str, Account]:
    rows = list(db.scalars(select(Account).where(Account.company_id == company_id)).all())
    existing = {row.code: row for row in rows}
    for code, name, account_type in DEFAULT_ACCOUNTS:
        if code not in existing:
            account = Account(
                company_id=company_id,
                code=code,
                name=name,
                account_type=account_type,
            )
            db.add(account)
            existing[code] = account
    db.flush()
    return existing


def list_accounts(db: Session, company_id: str | None) -> list[Account]:
    scoped_company_id = require_company_id(company_id)
    query = select(Account).where(Account.company_id == scoped_company_id)
    return list(db.scalars(query.order_by(Account.code)).all())


def create_account(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    payload: AccountCreate,
) -> Account:
    scoped_company_id = require_company_id(company_id)
    if db.scalar(
        select(Account.id).where(
            Account.company_id == scoped_company_id,
            Account.code == payload.code,
        )
    ):
        raise ServiceError(409, f"Account code already exists: {payload.code}.")
    account = Account(
        company_id=scoped_company_id,
        code=payload.code,
        name=payload.name,
        account_type=payload.account_type,
        parent_id=payload.parent_id,
        is_active=payload.is_active,
        metadata_json=payload.metadata,
    )
    db.add(account)
    db.flush()
    db.refresh(account)
    record_audit(
        db,
        action="accounting.account_created",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="account",
        entity_id=account.id,
        metadata={"code": account.code, "name": account.name},
    )
    return account


def update_account(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    account_id: str,
    payload: AccountUpdate,
) -> Account:
    scoped_company_id = require_company_id(company_id)
    account = db.scalar(
        select(Account).where(
            Account.company_id == scoped_company_id,
            Account.id == account_id,
        )
    )
    if account is None:
        raise ServiceError(404, "Account not found.")
    fields = payload.model_dump(exclude_unset=True)
    if "code" in fields and fields["code"] != account.code:
        if db.scalar(
            select(Account.id).where(
                Account.company_id == scoped_company_id,
                Account.code == fields["code"],
                Account.id != account.id,
            )
        ):
            raise ServiceError(409, f"Account code already exists: {fields['code']}.")
    for field in ("code", "name", "account_type", "parent_id", "is_active"):
        if field in fields:
            setattr(account, field, fields[field])
    if "metadata" in fields:
        account.metadata_json = fields["metadata"]
    db.flush()
    db.refresh(account)
    record_audit(
        db,
        action="accounting.account_updated",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="account",
        entity_id=account.id,
        metadata={"code": account.code, "name": account.name},
    )
    return account


def list_periods(db: Session, company_id: str | None) -> list[AccountingPeriod]:
    scoped_company_id = require_company_id(company_id)
    query = select(AccountingPeriod).where(AccountingPeriod.company_id == scoped_company_id)
    return list(db.scalars(query.order_by(AccountingPeriod.starts_at.desc())).all())


def create_period(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    payload: AccountingPeriodCreate,
) -> AccountingPeriod:
    scoped_company_id = require_company_id(company_id)
    if payload.ends_at <= payload.starts_at:
        raise ServiceError(422, "Accounting period end must be after the start.")
    period = AccountingPeriod(
        company_id=scoped_company_id,
        name=payload.name,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        status=payload.status,
        metadata_json=payload.metadata,
    )
    db.add(period)
    db.flush()
    db.refresh(period)
    record_audit(
        db,
        action="accounting.period_created",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="accounting_period",
        entity_id=period.id,
        metadata={"name": period.name, "status": period.status},
    )
    return period


def update_period(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    period_id: str,
    payload: AccountingPeriodUpdate,
) -> AccountingPeriod:
    scoped_company_id = require_company_id(company_id)
    period = db.scalar(
        select(AccountingPeriod).where(
            AccountingPeriod.company_id == scoped_company_id,
            AccountingPeriod.id == period_id,
        )
    )
    if period is None:
        raise ServiceError(404, "Accounting period not found.")
    fields = payload.model_dump(exclude_unset=True)
    for field in ("name", "starts_at", "ends_at", "status", "locked_at"):
        if field in fields:
            setattr(period, field, fields[field])
    if "metadata" in fields:
        period.metadata_json = fields["metadata"]
    if period.ends_at <= period.starts_at:
        raise ServiceError(422, "Accounting period end must be after the start.")
    if period.status not in ACCOUNTING_PERIOD_STATUSES:
        raise ServiceError(422, f"Unsupported accounting period status: {period.status}.")
    db.flush()
    db.refresh(period)
    record_audit(
        db,
        action="accounting.period_updated",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="accounting_period",
        entity_id=period.id,
        metadata={"status": period.status},
    )
    return period


def list_journal_entries(db: Session, company_id: str | None) -> list[JournalEntry]:
    scoped_company_id = require_company_id(company_id)
    query = select(JournalEntry).where(JournalEntry.company_id == scoped_company_id)
    return list(
        db.scalars(
            query.order_by(JournalEntry.posted_at.desc(), JournalEntry.created_at.desc())
        ).all()
    )


def get_journal_entry(db: Session, company_id: str | None, entry_id: str) -> JournalEntry:
    scoped_company_id = require_company_id(company_id)
    entry = db.scalar(
        select(JournalEntry).where(
            JournalEntry.company_id == scoped_company_id,
            JournalEntry.id == entry_id,
        )
    )
    if entry is None:
        raise ServiceError(404, "Journal entry not found.")
    return entry


def _validate_journal_lines(lines: Iterable[JournalLineCreate]) -> tuple[int, int]:
    debit_total = 0
    credit_total = 0
    has_lines = False
    for line in lines:
        has_lines = True
        if line.debit_minor and line.credit_minor:
            raise ServiceError(422, "A journal line cannot have both debit and credit values.")
        debit_total += line.debit_minor
        credit_total += line.credit_minor
    if not has_lines:
        raise ServiceError(422, "A journal entry requires at least one line.")
    if debit_total != credit_total:
        raise ServiceError(422, "Journal entry debits and credits must balance.")
    return debit_total, credit_total


def _ensure_period_is_open(
    db: Session,
    *,
    company_id: str,
    posted_at: Any | None,
) -> None:
    if posted_at is None:
        return
    period = db.scalar(
        select(AccountingPeriod).where(
            AccountingPeriod.company_id == company_id,
            AccountingPeriod.starts_at <= posted_at,
            AccountingPeriod.ends_at >= posted_at,
        )
    )
    if period and period.status in {"locked", "closed"}:
        raise ServiceError(409, "Accounting period is locked.")


def create_journal_entry(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    payload: JournalEntryCreate,
    post_authoritative: bool = True,
) -> JournalEntry:
    scoped_company_id = require_company_id(company_id)
    _validate_journal_lines(payload.lines)
    posted_at = payload.posted_at or utcnow()
    _ensure_period_is_open(db, company_id=scoped_company_id, posted_at=posted_at)
    if payload.source_type and payload.source_id:
        existing = db.scalar(
            select(JournalEntry).where(
                JournalEntry.company_id == scoped_company_id,
                JournalEntry.source_type == payload.source_type,
                JournalEntry.source_id == payload.source_id,
            )
        )
        if existing:
            return existing

    if post_authoritative and payload.status == "posted":
        from erp.packages.core.ledger_services import (
            ensure_default_ledger_accounts,
            post_journal,
        )

        ensure_default_ledger_accounts(db, scoped_company_id)
        ledger_by_legacy = {
            row.legacy_account_id: row
            for row in db.scalars(
                select(LedgerAccount).where(LedgerAccount.company_id == scoped_company_id)
            ).all()
            if row.legacy_account_id
        }
        authority_lines: list[LedgerLineCreate] = []
        for line in payload.lines:
            authority_account = ledger_by_legacy.get(line.account_id)
            if authority_account is None:
                raise ServiceError(422, "Legacy account is not mapped to the authoritative ledger.")
            authority_lines.append(
                LedgerLineCreate(
                    account_id=authority_account.id,
                    debit_minor=line.debit_minor,
                    credit_minor=line.credit_minor,
                    memo=line.memo,
                    metadata=line.metadata,
                )
            )
        source_type = payload.source_type or "legacy_manual"
        source_id = payload.source_id or new_uuid()
        post_journal(
            db,
            company_id=scoped_company_id,
            user_id=user_id,
            payload=LedgerJournalCreate(
                source_type=source_type,
                source_id=source_id,
                idempotency_key=f"legacy-adapter:{source_type}:{source_id}",
                memo=payload.memo or "Legacy accounting journal",
                posted_at=posted_at,
                metadata={**payload.metadata, "compatibility_adapter": True},
                lines=authority_lines,
            ),
            project_legacy=False,
        )

    entry = JournalEntry(
        company_id=scoped_company_id,
        entry_number=payload.entry_number or generate_entry_number(),
        source_type=payload.source_type,
        source_id=payload.source_id,
        memo=payload.memo,
        status=payload.status,
        posted_at=posted_at,
        created_by_id=user_id,
        metadata_json=payload.metadata,
    )
    db.add(entry)
    db.flush()

    for line in payload.lines:
        db.add(
            JournalLine(
                company_id=scoped_company_id,
                journal_entry_id=entry.id,
                account_id=line.account_id,
                debit_minor=line.debit_minor,
                credit_minor=line.credit_minor,
                memo=line.memo,
                metadata_json=line.metadata,
            )
        )
    db.flush()
    db.refresh(entry)
    record_audit(
        db,
        action="accounting.journal_posted",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="journal_entry",
        entity_id=entry.id,
        metadata={"entry_number": entry.entry_number, "source_type": entry.source_type},
    )
    return entry


def list_vendor_ledger_entries(
    db: Session,
    company_id: str | None,
    *,
    vendor_id: str | None = None,
) -> list[VendorLedgerEntry]:
    scoped_company_id = require_company_id(company_id)
    query = select(VendorLedgerEntry).where(VendorLedgerEntry.company_id == scoped_company_id)
    if vendor_id:
        query = query.where(VendorLedgerEntry.vendor_id == vendor_id)
    return list(db.scalars(query.order_by(VendorLedgerEntry.created_at)).all())


def vendor_balance_minor(db: Session, company_id: str, vendor_id: str) -> int:
    return int(
        db.scalar(
            select(func.coalesce(func.sum(VendorLedgerEntry.amount_minor), 0)).where(
                VendorLedgerEntry.company_id == company_id,
                VendorLedgerEntry.vendor_id == vendor_id,
            )
        )
        or 0
    )


def append_vendor_ledger_entry(
    db: Session,
    *,
    company_id: str,
    vendor_id: str,
    entry_type: str,
    amount_minor: int,
    source_type: str | None = None,
    source_id: str | None = None,
    memo: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> VendorLedgerEntry:
    balance = vendor_balance_minor(db, company_id, vendor_id) + amount_minor
    entry = VendorLedgerEntry(
        company_id=company_id,
        vendor_id=vendor_id,
        entry_type=entry_type,
        source_type=source_type,
        source_id=source_id,
        amount_minor=amount_minor,
        balance_minor=balance,
        memo=memo,
        metadata_json=metadata or {},
    )
    db.add(entry)
    db.flush()
    return entry


def list_cash_books(db: Session, company_id: str | None) -> list[CashBook]:
    scoped_company_id = require_company_id(company_id)
    query = select(CashBook).where(CashBook.company_id == scoped_company_id)
    return list(db.scalars(query.order_by(CashBook.code)).all())


def create_cash_book(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    payload: CashBookCreate,
) -> CashBook:
    scoped_company_id = require_company_id(company_id)
    if db.scalar(
        select(CashBook.id).where(
            CashBook.company_id == scoped_company_id,
            CashBook.code == payload.code,
        )
    ):
        raise ServiceError(409, f"Cash book already exists: {payload.code}.")
    book = CashBook(
        company_id=scoped_company_id,
        code=payload.code,
        name=payload.name,
        currency=payload.currency,
        opening_balance_minor=payload.opening_balance_minor,
        is_active=payload.is_active,
        metadata_json=payload.metadata,
    )
    db.add(book)
    db.flush()
    db.refresh(book)
    record_audit(
        db,
        action="accounting.cash_book_created",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="cash_book",
        entity_id=book.id,
        metadata={"code": book.code, "name": book.name},
    )
    return book


def list_bank_accounts(db: Session, company_id: str | None) -> list[BankAccount]:
    scoped_company_id = require_company_id(company_id)
    query = select(BankAccount).where(BankAccount.company_id == scoped_company_id)
    return list(db.scalars(query.order_by(BankAccount.code)).all())


def create_bank_account(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    payload: BankAccountCreate,
) -> BankAccount:
    scoped_company_id = require_company_id(company_id)
    if db.scalar(
        select(BankAccount.id).where(
            BankAccount.company_id == scoped_company_id,
            BankAccount.code == payload.code,
        )
    ):
        raise ServiceError(409, f"Bank account already exists: {payload.code}.")
    account = BankAccount(
        company_id=scoped_company_id,
        code=payload.code,
        bank_name=payload.bank_name,
        account_name=payload.account_name,
        account_number=payload.account_number,
        iban=payload.iban,
        currency=payload.currency,
        opening_balance_minor=payload.opening_balance_minor,
        is_active=payload.is_active,
        metadata_json=payload.metadata,
    )
    db.add(account)
    db.flush()
    db.refresh(account)
    record_audit(
        db,
        action="accounting.bank_account_created",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="bank_account",
        entity_id=account.id,
        metadata={"code": account.code, "bank_name": account.bank_name},
    )
    return account


def list_expenses(db: Session, company_id: str | None) -> list[Expense]:
    scoped_company_id = require_company_id(company_id)
    query = select(Expense).where(Expense.company_id == scoped_company_id)
    return list(
        db.scalars(query.order_by(Expense.incurred_at.desc(), Expense.created_at.desc())).all()
    )


def create_expense(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    payload: ExpenseCreate,
) -> Expense:
    scoped_company_id = require_company_id(company_id)
    expense = Expense(
        company_id=scoped_company_id,
        expense_number=payload.expense_number or generate_entry_number("EXP"),
        account_id=payload.account_id,
        vendor_id=payload.vendor_id,
        cash_book_id=payload.cash_book_id,
        bank_account_id=payload.bank_account_id,
        amount_minor=payload.amount_minor,
        currency=payload.currency,
        status=payload.status,
        memo=payload.memo,
        incurred_at=payload.incurred_at,
        paid_at=payload.paid_at,
        metadata_json=payload.metadata,
    )
    db.add(expense)
    db.flush()
    db.refresh(expense)
    if expense.status == "paid" and expense.amount_minor > 0:
        from erp.packages.core.ledger_services import (
            ensure_default_ledger_accounts,
            post_journal,
        )

        ledger_accounts = ensure_default_ledger_accounts(db, scoped_company_id)
        expense_account = db.scalar(
            select(LedgerAccount).where(
                LedgerAccount.company_id == scoped_company_id,
                LedgerAccount.legacy_account_id == expense.account_id,
            )
        )
        if expense_account is None:
            raise ServiceError(422, "Expense account is not mapped to the authoritative ledger.")
        post_journal(
            db,
            company_id=scoped_company_id,
            user_id=user_id,
            payload=LedgerJournalCreate(
                source_type="expense",
                source_id=expense.id,
                idempotency_key=f"expense:{expense.id}",
                memo=expense.memo or f"Expense {expense.expense_number}",
                posted_at=expense.paid_at or expense.incurred_at or utcnow(),
                metadata={"expense_id": expense.id},
                lines=[
                    LedgerLineCreate(
                        account_id=expense_account.id,
                        debit_minor=expense.amount_minor,
                        currency=expense.currency,
                    ),
                    LedgerLineCreate(
                        account_id=ledger_accounts["1010"].id,
                        credit_minor=expense.amount_minor,
                        currency=expense.currency,
                    ),
                ],
            ),
        )
    record_audit(
        db,
        action="accounting.expense_created",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="expense",
        entity_id=expense.id,
        metadata={"expense_number": expense.expense_number, "amount_minor": expense.amount_minor},
    )
    return expense


def post_order_payment_entry(
    db: Session,
    *,
    company_id: str,
    user_id: str,
    order: Order,
    payment: Payment,
    vendor_items: list[VendorOrderItem] | None = None,
) -> JournalEntry:
    if payment.amount_minor <= 0:
        raise ServiceError(422, "Payment amount must be positive.")
    existing = db.scalar(
        select(JournalEntry).where(
            JournalEntry.company_id == company_id,
            JournalEntry.source_type == "payment",
            JournalEntry.source_id == payment.id,
        )
    )
    if existing:
        return existing

    accounts = ensure_default_accounts(db, company_id)
    lines: list[JournalLineCreate] = [
        JournalLineCreate(
            account_id=accounts["1000"].id,
            debit_minor=payment.amount_minor,
            metadata={"order_id": order.id, "payment_id": payment.id},
        )
    ]

    items = vendor_items
    if items is None:
        items = list(
            db.scalars(
                select(VendorOrderItem).where(
                    VendorOrderItem.company_id == company_id,
                    VendorOrderItem.order_id == order.id,
                )
            ).all()
        )

    vendor_payables: dict[str, int] = {}
    commission_total = 0
    for item in items:
        vendor_payables[item.vendor_id] = (
            vendor_payables.get(item.vendor_id, 0) + item.payable_minor
        )
        commission_total += item.commission_minor

    # Legacy projections must also support partial payments. The authoritative
    # vendor liability is deliberately created later by finance approval.
    allocation_ratio = min(1.0, payment.amount_minor / max(1, order.total_minor))
    vendor_payables = {
        vendor_id: int(round(amount * allocation_ratio))
        for vendor_id, amount in vendor_payables.items()
    }
    commission_total = int(round(commission_total * allocation_ratio))
    vendor_payable_total = sum(vendor_payables.values())
    remainder = payment.amount_minor - vendor_payable_total - commission_total
    if remainder < 0:
        raise ServiceError(422, "Payment allocation could not be balanced.")

    # Post to the authoritative ledger first. Ownership policy changes the
    # financial treatment while the legacy projection below preserves existing
    # API behavior during the compatibility window.
    from erp.packages.core.ledger_services import (
        ensure_default_ledger_accounts,
        post_journal,
    )

    ledger_accounts = ensure_default_ledger_accounts(db, company_id)
    collection_rider_id = str(payment.metadata_json.get("rider_user_id") or "").strip()
    cash_account_code = "1020" if collection_rider_id else "1000"
    authority_lines: list[LedgerLineCreate] = [
        LedgerLineCreate(
            account_id=ledger_accounts[cash_account_code].id,
            debit_minor=payment.amount_minor,
            currency=payment.currency,
            metadata={"order_id": order.id, "payment_id": payment.id},
        )
    ]
    # Customer collection is revenue; vendors only become a real liability after
    # finance explicitly approves a successfully delivered, fully paid sale.
    # This stops an uncollected, returned, or disputed COD order from inflating
    # vendor payables. The legacy projection below is retained for historical
    # compatibility but is not the authority for settlement eligibility.
    authority_lines.append(
        LedgerLineCreate(
            account_id=ledger_accounts["4000"].id,
            credit_minor=payment.amount_minor,
            currency=payment.currency,
        )
    )
    post_journal(
        db,
        company_id=company_id,
        user_id=user_id,
        payload=LedgerJournalCreate(
            source_type="payment",
            source_id=payment.id,
            idempotency_key=f"payment:{payment.id}",
            memo=f"Payment for order {order.order_number}",
            posted_at=payment.paid_at or utcnow(),
            metadata={
                "order_id": order.id,
                "payment_id": payment.id,
                "rider_user_id": collection_rider_id or None,
            },
            lines=authority_lines,
        ),
        project_legacy=False,
    )

    if vendor_payable_total:
        lines.append(
            JournalLineCreate(
                account_id=accounts["2000"].id,
                credit_minor=vendor_payable_total,
                metadata={"order_id": order.id, "payment_id": payment.id},
            )
        )
    if commission_total:
        lines.append(
            JournalLineCreate(
                account_id=accounts["3000"].id,
                credit_minor=commission_total,
                metadata={"order_id": order.id, "payment_id": payment.id},
            )
        )
    if remainder:
        lines.append(
            JournalLineCreate(
                account_id=accounts["4000"].id,
                credit_minor=remainder,
                metadata={"order_id": order.id, "payment_id": payment.id},
            )
        )

    entry = create_journal_entry(
        db,
        company_id=company_id,
        user_id=user_id,
        payload=JournalEntryCreate(
            entry_number=generate_entry_number(),
            source_type="payment",
            source_id=payment.id,
            memo=f"Payment for order {order.order_number}",
            posted_at=payment.paid_at or utcnow(),
            metadata={"order_id": order.id, "payment_id": payment.id},
            lines=lines,
        ),
        post_authoritative=False,
    )

    for vendor_id, payable_minor in vendor_payables.items():
        append_vendor_ledger_entry(
            db,
            company_id=company_id,
            vendor_id=vendor_id,
            entry_type="sale",
            amount_minor=payable_minor,
            source_type="payment",
            source_id=payment.id,
            memo=f"Vendor payable for order {order.order_number}",
            metadata={
                "order_id": order.id,
                "payment_id": payment.id,
                "finance_status": "pending_approval",
                "legacy_projection": True,
            },
        )
    return entry


def post_vendor_settlement_entry(
    db: Session,
    *,
    company_id: str,
    user_id: str,
    settlement: VendorSettlement,
) -> JournalEntry:
    existing = db.scalar(
        select(JournalEntry).where(
            JournalEntry.company_id == company_id,
            JournalEntry.source_type == "settlement",
            JournalEntry.source_id == settlement.id,
        )
    )
    if existing:
        return existing

    accounts = ensure_default_accounts(db, company_id)
    cash_account = accounts["1010"].id
    if settlement.payable_minor <= 0:
        raise ServiceError(422, "Settlement payable amount must be positive.")

    from erp.packages.core.ledger_services import (
        ensure_default_ledger_accounts,
        post_journal,
    )

    ledger_accounts = ensure_default_ledger_accounts(db, company_id)
    post_journal(
        db,
        company_id=company_id,
        user_id=user_id,
        payload=LedgerJournalCreate(
            source_type="settlement",
            source_id=settlement.id,
            idempotency_key=f"settlement:{settlement.id}",
            memo=f"Vendor settlement {settlement.settlement_number}",
            posted_at=settlement.paid_at or utcnow(),
            metadata={"vendor_id": settlement.vendor_id, "settlement_id": settlement.id},
            lines=[
                LedgerLineCreate(
                    account_id=ledger_accounts["2000"].id,
                    vendor_id=settlement.vendor_id,
                    debit_minor=settlement.payable_minor,
                    currency=settlement.currency,
                ),
                LedgerLineCreate(
                    account_id=ledger_accounts["1010"].id,
                    credit_minor=settlement.payable_minor,
                    currency=settlement.currency,
                ),
            ],
        ),
        project_legacy=False,
    )

    entry = create_journal_entry(
        db,
        company_id=company_id,
        user_id=user_id,
        payload=JournalEntryCreate(
            entry_number=generate_entry_number("SETT"),
            source_type="settlement",
            source_id=settlement.id,
            memo=f"Vendor settlement {settlement.settlement_number}",
            posted_at=settlement.paid_at or utcnow(),
            metadata={"vendor_id": settlement.vendor_id, "settlement_id": settlement.id},
            lines=[
                JournalLineCreate(
                    account_id=accounts["2000"].id,
                    debit_minor=settlement.payable_minor,
                    metadata={"settlement_id": settlement.id},
                ),
                JournalLineCreate(
                    account_id=cash_account,
                    credit_minor=settlement.payable_minor,
                    metadata={"settlement_id": settlement.id},
                ),
            ],
        ),
        post_authoritative=False,
    )
    append_vendor_ledger_entry(
        db,
        company_id=company_id,
        vendor_id=settlement.vendor_id,
        entry_type="settlement",
        amount_minor=-settlement.payable_minor,
        source_type="settlement",
        source_id=settlement.id,
        memo=f"Settlement {settlement.settlement_number}",
        metadata={"settlement_id": settlement.id},
    )
    settlement.status = "paid"
    settlement.paid_minor = settlement.payable_minor
    settlement.paid_at = settlement.paid_at or utcnow()
    settlement.journal_entry_id = entry.id
    db.flush()
    record_audit(
        db,
        action="accounting.vendor_settlement_posted",
        company_id=company_id,
        user_id=user_id,
        entity_type="vendor_settlement",
        entity_id=settlement.id,
        metadata={"vendor_id": settlement.vendor_id, "payable_minor": settlement.payable_minor},
    )
    return entry


def list_cashes_and_banks_and_expenses(db: Session, company_id: str | None) -> dict[str, list[Any]]:
    return {
        "cash_books": list_cash_books(db, company_id),
        "bank_accounts": list_bank_accounts(db, company_id),
        "expenses": list_expenses(db, company_id),
    }
