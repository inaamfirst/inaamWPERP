from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from erp.packages.core import accounting_services
from erp.packages.core.api.dependencies import DbSession, require_permission, service_error_to_http
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
    VendorLedgerEntryOut,
)
from erp.packages.core.services import AuthContext, ServiceError

router = APIRouter()

AccountingViewContext = Annotated[
    AuthContext,
    Depends(require_permission("accounting.view")),
]
AccountingPostContext = Annotated[
    AuthContext,
    Depends(require_permission("accounting.post")),
]
AccountingManageContext = Annotated[
    AuthContext,
    Depends(require_permission("accounting.manage_accounts")),
]
AccountingReconcileContext = Annotated[
    AuthContext,
    Depends(require_permission("accounting.reconcile")),
]


def _company_id(context: AuthContext) -> str:
    if not context.user.company_id:
        raise ServiceError(403, "A company-scoped user is required.")
    return context.user.company_id


@router.get("/accounting/accounts", response_model=list[AccountOut], tags=["accounting"])
def accounts_list(context: AccountingViewContext, db: DbSession) -> list[AccountOut]:
    try:
        accounts = accounting_services.list_accounts(db, context.user.company_id)
        return [accounting_services.account_out(account) for account in accounts]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.post(
    "/accounting/accounts",
    response_model=AccountOut,
    status_code=201,
    tags=["accounting"],
)
def account_create(
    payload: AccountCreate,
    context: AccountingManageContext,
    db: DbSession,
) -> AccountOut:
    try:
        account = accounting_services.create_account(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            payload=payload,
        )
        db.commit()
        return accounting_services.account_out(account)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.put(
    "/accounting/accounts/{account_id}",
    response_model=AccountOut,
    status_code=200,
    tags=["accounting"],
)
def account_update(
    account_id: str,
    payload: AccountUpdate,
    context: AccountingManageContext,
    db: DbSession,
) -> AccountOut:
    try:
        account = accounting_services.update_account(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            account_id=account_id,
            payload=payload,
        )
        db.commit()
        return accounting_services.account_out(account)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get("/accounting/periods", response_model=list[AccountingPeriodOut], tags=["accounting"])
def periods_list(context: AccountingViewContext, db: DbSession) -> list[AccountingPeriodOut]:
    try:
        return [
            accounting_services.period_out(period)
            for period in accounting_services.list_periods(db, context.user.company_id)
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.post(
    "/accounting/periods",
    response_model=AccountingPeriodOut,
    status_code=201,
    tags=["accounting"],
)
def period_create(
    payload: AccountingPeriodCreate,
    context: AccountingReconcileContext,
    db: DbSession,
) -> AccountingPeriodOut:
    try:
        period = accounting_services.create_period(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            payload=payload,
        )
        db.commit()
        return accounting_services.period_out(period)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.put(
    "/accounting/periods/{period_id}",
    response_model=AccountingPeriodOut,
    status_code=200,
    tags=["accounting"],
)
def period_update(
    period_id: str,
    payload: AccountingPeriodUpdate,
    context: AccountingReconcileContext,
    db: DbSession,
) -> AccountingPeriodOut:
    try:
        period = accounting_services.update_period(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            period_id=period_id,
            payload=payload,
        )
        db.commit()
        return accounting_services.period_out(period)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get(
    "/accounting/journal-entries",
    response_model=list[JournalEntryOut],
    tags=["accounting"],
)
def journal_entries_list(context: AccountingViewContext, db: DbSession) -> list[JournalEntryOut]:
    try:
        return [
            accounting_services.journal_entry_out(db, entry)
            for entry in accounting_services.list_journal_entries(db, context.user.company_id)
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.get(
    "/accounting/journal-entries/{entry_id}",
    response_model=JournalEntryOut,
    tags=["accounting"],
)
def journal_entry_detail(
    entry_id: str,
    context: AccountingViewContext,
    db: DbSession,
) -> JournalEntryOut:
    try:
        return accounting_services.journal_entry_out(
            db,
            accounting_services.get_journal_entry(db, context.user.company_id, entry_id),
        )
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.post(
    "/accounting/journal-entries",
    response_model=JournalEntryOut,
    status_code=201,
    tags=["accounting"],
)
def journal_entry_create(
    payload: JournalEntryCreate,
    context: AccountingPostContext,
    db: DbSession,
) -> JournalEntryOut:
    try:
        entry = accounting_services.create_journal_entry(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            payload=payload,
        )
        db.commit()
        return accounting_services.journal_entry_out(db, entry)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get(
    "/accounting/vendor-ledger",
    response_model=list[VendorLedgerEntryOut],
    tags=["accounting"],
)
def vendor_ledger_list(
    context: AccountingViewContext,
    db: DbSession,
    vendor_id: str | None = None,
) -> list[VendorLedgerEntryOut]:
    try:
        return [
            accounting_services.vendor_ledger_entry_out(entry)
            for entry in accounting_services.list_vendor_ledger_entries(
                db,
                context.user.company_id,
                vendor_id=vendor_id,
            )
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.get("/accounting/cash-books", response_model=list[CashBookOut], tags=["accounting"])
def cash_books_list(context: AccountingViewContext, db: DbSession) -> list[CashBookOut]:
    try:
        return [
            accounting_services.cash_book_out(book)
            for book in accounting_services.list_cash_books(db, context.user.company_id)
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.post(
    "/accounting/cash-books",
    response_model=CashBookOut,
    status_code=201,
    tags=["accounting"],
)
def cash_book_create(
    payload: CashBookCreate,
    context: AccountingManageContext,
    db: DbSession,
) -> CashBookOut:
    try:
        book = accounting_services.create_cash_book(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            payload=payload,
        )
        db.commit()
        return accounting_services.cash_book_out(book)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get("/accounting/bank-accounts", response_model=list[BankAccountOut], tags=["accounting"])
def bank_accounts_list(context: AccountingViewContext, db: DbSession) -> list[BankAccountOut]:
    try:
        return [
            accounting_services.bank_account_out(account)
            for account in accounting_services.list_bank_accounts(db, context.user.company_id)
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.post(
    "/accounting/bank-accounts",
    response_model=BankAccountOut,
    status_code=201,
    tags=["accounting"],
)
def bank_account_create(
    payload: BankAccountCreate,
    context: AccountingManageContext,
    db: DbSession,
) -> BankAccountOut:
    try:
        account = accounting_services.create_bank_account(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            payload=payload,
        )
        db.commit()
        return accounting_services.bank_account_out(account)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get("/accounting/expenses", response_model=list[ExpenseOut], tags=["accounting"])
def expenses_list(context: AccountingViewContext, db: DbSession) -> list[ExpenseOut]:
    try:
        return [
            accounting_services.expense_out(expense)
            for expense in accounting_services.list_expenses(db, context.user.company_id)
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.post(
    "/accounting/expenses",
    response_model=ExpenseOut,
    status_code=201,
    tags=["accounting"],
)
def expense_create(
    payload: ExpenseCreate,
    context: AccountingPostContext,
    db: DbSession,
) -> ExpenseOut:
    try:
        expense = accounting_services.create_expense(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            payload=payload,
        )
        db.commit()
        return accounting_services.expense_out(expense)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc
