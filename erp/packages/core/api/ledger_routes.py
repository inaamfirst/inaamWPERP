from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select

from erp.packages.core import ledger_services, marketplace_services
from erp.packages.core.api.dependencies import DbSession, require_permission, service_error_to_http
from erp.packages.core.db.models import (
    LedgerAccount,
    LedgerJournal,
    LedgerLine,
    LedgerPeriod,
    Vendor,
    VendorUser,
)
from erp.packages.core.schemas import (
    AuditLogOut,
    LedgerAccountOut,
    LedgerJournalCreate,
    LedgerJournalOut,
    LedgerLineOut,
    LedgerOverviewOut,
    LedgerPeriodCreate,
    LedgerPeriodOut,
    LedgerPeriodStatusRequest,
    LedgerReverseRequest,
    ReconciliationIssueOut,
    TrialBalanceRow,
    VendorInventoryBalanceOut,
    VendorInventoryMovementCreate,
    VendorInventoryMovementOut,
    VendorLedgerLineOut,
    VendorLedgerOverviewOut,
    VendorOrderItemOut,
    VendorSettlementOut,
)
from erp.packages.core.services import AuthContext, ServiceError

router = APIRouter()

LedgerViewContext = Annotated[AuthContext, Depends(require_permission("ledger.view"))]
LedgerPostContext = Annotated[AuthContext, Depends(require_permission("ledger.post"))]
LedgerReverseContext = Annotated[AuthContext, Depends(require_permission("ledger.reverse"))]
LedgerPeriodsContext = Annotated[AuthContext, Depends(require_permission("ledger.manage_periods"))]
LedgerExportContext = Annotated[AuthContext, Depends(require_permission("ledger.export"))]
VendorLedgerContext = Annotated[AuthContext, Depends(require_permission("vendor.ledger.view"))]
VendorStockContext = Annotated[AuthContext, Depends(require_permission("vendor.stock.view"))]
VendorReportsContext = Annotated[AuthContext, Depends(require_permission("vendor.reports.view"))]
VendorStockManageContext = Annotated[
    AuthContext, Depends(require_permission("vendor.stock.manage"))
]
PageOffset = Annotated[int, Query(ge=0)]
PageLimit = Annotated[int, Query(ge=1, le=500)]


def company_id(context: AuthContext) -> str:
    if not context.user.company_id:
        error = ServiceError(403, "A company-scoped user is required.")
        raise service_error_to_http(error) from error
    return context.user.company_id


def own_vendor(db: DbSession, context: AuthContext) -> Vendor:
    scoped = company_id(context)
    vendor = db.scalar(
        select(Vendor)
        .join(VendorUser, VendorUser.vendor_id == Vendor.id)
        .where(
            Vendor.company_id == scoped,
            VendorUser.company_id == scoped,
            VendorUser.user_id == context.user.id,
        )
    )
    if vendor is None:
        error = ServiceError(404, "Vendor profile not found for the current user.")
        raise service_error_to_http(error) from error
    if vendor.status != "active":
        error = ServiceError(403, f"Vendor account is {vendor.status}.")
        raise service_error_to_http(error) from error
    return vendor


def validate_date_range(date_from: datetime | None, date_to: datetime | None) -> None:
    if date_from is not None and date_to is not None and date_from > date_to:
        error = ServiceError(422, "date_from must not be later than date_to.")
        raise service_error_to_http(error) from error


def account_out(row: LedgerAccount) -> LedgerAccountOut:
    return LedgerAccountOut(
        id=row.id,
        company_id=row.company_id,
        code=row.code,
        name=row.name,
        account_type=row.account_type,
        parent_id=row.parent_id,
        is_active=row.is_active,
        currency=row.currency,
        metadata=row.metadata_json,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def line_out(row: LedgerLine) -> LedgerLineOut:
    return LedgerLineOut(
        id=row.id,
        journal_id=row.journal_id,
        company_id=row.company_id,
        account_id=row.account_id,
        vendor_id=row.vendor_id,
        debit_minor=row.debit_minor,
        credit_minor=row.credit_minor,
        currency=row.currency,
        memo=row.memo,
        metadata=row.metadata_json,
    )


def journal_out(db: DbSession, row: LedgerJournal) -> LedgerJournalOut:
    return LedgerJournalOut(
        id=row.id,
        company_id=row.company_id,
        entry_number=row.entry_number,
        source_type=row.source_type,
        source_id=row.source_id,
        idempotency_key=row.idempotency_key,
        status=row.status,
        posted_at=row.posted_at,
        created_by_id=row.created_by_id,
        reversal_of_id=row.reversal_of_id,
        memo=row.memo,
        metadata=row.metadata_json,
        lines=[line_out(line) for line in ledger_services.journal_lines(db, row.id)],
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def period_out(row: LedgerPeriod) -> LedgerPeriodOut:
    return LedgerPeriodOut(
        id=row.id,
        company_id=row.company_id,
        name=row.name,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        status=row.status,
        locked_at=row.locked_at,
        closed_at=row.closed_at,
        closed_by_id=row.closed_by_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def inventory_balance_out(row) -> VendorInventoryBalanceOut:  # type: ignore[no-untyped-def]
    return VendorInventoryBalanceOut(
        id=row.id,
        company_id=row.company_id,
        vendor_id=row.vendor_id,
        product_id=row.product_id,
        variant_id=row.variant_id,
        warehouse_id=row.warehouse_id,
        ownership_type=row.ownership_type,
        on_hand_quantity=row.on_hand_quantity,
        reserved_quantity=row.reserved_quantity,
        available_quantity=row.available_quantity,
        unit_cost_minor=row.unit_cost_minor,
        currency=row.currency,
        last_movement_at=row.last_movement_at,
    )


def inventory_movement_out(row) -> VendorInventoryMovementOut:  # type: ignore[no-untyped-def]
    return VendorInventoryMovementOut(
        id=row.id,
        company_id=row.company_id,
        vendor_id=row.vendor_id,
        product_id=row.product_id,
        variant_id=row.variant_id,
        warehouse_id=row.warehouse_id,
        movement_type=row.movement_type,
        quantity_delta=row.quantity_delta,
        quantity_before=row.quantity_before,
        quantity_after=row.quantity_after,
        reserved_quantity_delta=row.reserved_quantity_delta,
        ownership_type=row.ownership_type,
        unit_cost_minor=row.unit_cost_minor,
        valuation_minor=row.valuation_minor,
        currency=row.currency,
        source_type=row.source_type,
        source_id=row.source_id,
        transfer_group_id=row.transfer_group_id,
        occurred_at=row.occurred_at,
        reason=row.reason,
        metadata=row.metadata_json,
        created_at=row.created_at,
    )


def audit_out(row) -> AuditLogOut:  # type: ignore[no-untyped-def]
    return AuditLogOut(
        id=row.id,
        company_id=row.company_id,
        user_id=row.user_id,
        action=row.action,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        metadata=row.metadata_json,
        created_at=row.created_at,
    )


def handle_read(call):  # type: ignore[no-untyped-def]
    try:
        return call()
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.get("/ledger/overview", response_model=LedgerOverviewOut, tags=["ledger"])
def ledger_overview(context: LedgerViewContext, db: DbSession) -> LedgerOverviewOut:
    return LedgerOverviewOut(
        **handle_read(lambda: ledger_services.company_overview(db, company_id(context)))
    )


@router.get("/ledger/accounts", response_model=list[LedgerAccountOut], tags=["ledger"])
def ledger_accounts(context: LedgerViewContext, db: DbSession) -> list[LedgerAccountOut]:
    rows = handle_read(lambda: ledger_services.list_accounts(db, company_id(context)))
    db.commit()  # default account mirroring is an intentional compatibility projection
    return [account_out(row) for row in rows]


@router.get("/ledger/periods", response_model=list[LedgerPeriodOut], tags=["ledger"])
def ledger_periods(context: LedgerViewContext, db: DbSession) -> list[LedgerPeriodOut]:
    scoped = company_id(context)
    rows = list(
        db.scalars(
            select(LedgerPeriod)
            .where(LedgerPeriod.company_id == scoped)
            .order_by(LedgerPeriod.starts_at.desc())
        ).all()
    )
    return [period_out(row) for row in rows]


@router.post("/ledger/periods", response_model=LedgerPeriodOut, status_code=201, tags=["ledger"])
def ledger_period_create(
    payload: LedgerPeriodCreate,
    context: LedgerPeriodsContext,
    db: DbSession,
) -> LedgerPeriodOut:
    try:
        row = ledger_services.create_period(
            db,
            company_id=company_id(context),
            user_id=context.user.id,
            payload=payload,
        )
        db.commit()
        return period_out(row)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.patch("/ledger/periods/{period_id}", response_model=LedgerPeriodOut, tags=["ledger"])
def ledger_period_status(
    period_id: str,
    payload: LedgerPeriodStatusRequest,
    context: LedgerPeriodsContext,
    db: DbSession,
) -> LedgerPeriodOut:
    try:
        row = ledger_services.set_period_status(
            db,
            company_id=company_id(context),
            user_id=context.user.id,
            period_id=period_id,
            status=payload.status,
            reason=payload.reason,
        )
        db.commit()
        return period_out(row)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get("/ledger/journals", response_model=list[LedgerJournalOut], tags=["ledger"])
def ledger_journals(
    context: LedgerViewContext,
    db: DbSession,
    vendor_id: str | None = None,
    account_id: str | None = None,
    source_type: str | None = None,
    status: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    offset: PageOffset = 0,
    limit: PageLimit = 100,
) -> list[LedgerJournalOut]:
    validate_date_range(date_from, date_to)
    rows = handle_read(
        lambda: ledger_services.list_journals(
            db,
            company_id(context),
            vendor_id=vendor_id,
            account_id=account_id,
            source_type=source_type,
            status=status,
            date_from=date_from,
            date_to=date_to,
            offset=offset,
            limit=limit,
        )
    )
    return [journal_out(db, row) for row in rows]


@router.get("/ledger/journals/{journal_id}", response_model=LedgerJournalOut, tags=["ledger"])
def ledger_journal_detail(
    journal_id: str,
    context: LedgerViewContext,
    db: DbSession,
) -> LedgerJournalOut:
    row = handle_read(lambda: ledger_services.get_journal(db, company_id(context), journal_id))
    return journal_out(db, row)


@router.post("/ledger/journals", response_model=LedgerJournalOut, status_code=201, tags=["ledger"])
def ledger_journal_post(
    payload: LedgerJournalCreate,
    context: LedgerPostContext,
    db: DbSession,
) -> LedgerJournalOut:
    try:
        row = ledger_services.post_journal(
            db,
            company_id=company_id(context),
            user_id=context.user.id,
            payload=payload,
        )
        db.commit()
        return journal_out(db, row)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.post(
    "/ledger/journals/{journal_id}/reverse", response_model=LedgerJournalOut, tags=["ledger"]
)
def ledger_journal_reverse(
    journal_id: str,
    payload: LedgerReverseRequest,
    context: LedgerReverseContext,
    db: DbSession,
) -> LedgerJournalOut:
    try:
        row = ledger_services.reverse_journal(
            db,
            company_id=company_id(context),
            user_id=context.user.id,
            journal_id=journal_id,
            reason=payload.reason,
            idempotency_key=payload.idempotency_key,
        )
        db.commit()
        return journal_out(db, row)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get("/ledger/trial-balance", response_model=list[TrialBalanceRow], tags=["ledger"])
def ledger_trial_balance(
    context: LedgerViewContext,
    db: DbSession,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[TrialBalanceRow]:
    validate_date_range(date_from, date_to)
    rows = handle_read(
        lambda: ledger_services.trial_balance(
            db, company_id(context), date_from=date_from, date_to=date_to
        )
    )
    return [TrialBalanceRow(**row) for row in rows]


@router.get("/ledger/reports/profit-loss", response_model=dict[str, Any], tags=["ledger"])
def profit_loss(
    context: LedgerViewContext,
    db: DbSession,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, Any]:
    validate_date_range(date_from, date_to)
    statement = handle_read(
        lambda: ledger_services.financial_statement(
            db,
            company_id(context),
            {"income", "expense"},
            date_from=date_from,
            date_to=date_to,
        )
    )
    income = sum(
        row["statement_balance_minor"]
        for row in statement["rows"]
        if row["account_type"] == "income"
    )
    expenses = sum(
        row["statement_balance_minor"]
        for row in statement["rows"]
        if row["account_type"] == "expense"
    )
    return {
        **statement,
        "income_minor": income,
        "expenses_minor": expenses,
        "profit_minor": income - expenses,
    }


@router.get("/ledger/reports/balance-sheet", response_model=dict[str, Any], tags=["ledger"])
def balance_sheet(
    context: LedgerViewContext,
    db: DbSession,
    date_to: datetime | None = None,
) -> dict[str, Any]:
    return handle_read(
        lambda: ledger_services.financial_statement(
            db,
            company_id(context),
            {"asset", "liability", "equity", "contra"},
            date_to=date_to,
        )
    )


@router.get("/ledger/reports/cash-flow", response_model=dict[str, Any], tags=["ledger"])
def cash_flow(
    context: LedgerViewContext,
    db: DbSession,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, Any]:
    validate_date_range(date_from, date_to)
    rows = handle_read(
        lambda: ledger_services.trial_balance(
            db, company_id(context), date_from=date_from, date_to=date_to
        )
    )
    cash_rows = [row for row in rows if row["account_code"] in {"1000", "1010"}]
    return {
        "rows": cash_rows,
        "net_cash_change_minor": sum(row["balance_minor"] for row in cash_rows),
    }


@router.get("/ledger/reports/vendor-payables", response_model=list[dict[str, Any]], tags=["ledger"])
def vendor_payables(
    context: LedgerViewContext,
    db: DbSession,
    as_of: datetime | None = None,
) -> list[dict[str, Any]]:
    return handle_read(
        lambda: ledger_services.vendor_payables_report(db, company_id(context), as_of=as_of)
    )


@router.get(
    "/ledger/reports/inventory", response_model=list[VendorInventoryBalanceOut], tags=["ledger"]
)
def inventory_report(
    context: LedgerViewContext,
    db: DbSession,
    vendor_id: str | None = None,
    product_id: str | None = None,
    warehouse_id: str | None = None,
) -> list[VendorInventoryBalanceOut]:
    rows = ledger_services.list_vendor_inventory_balances(
        db,
        company_id(context),
        vendor_id,
        product_id=product_id,
        warehouse_id=warehouse_id,
    )
    return [inventory_balance_out(row) for row in rows]


@router.get("/ledger/reconciliation", response_model=list[ReconciliationIssueOut], tags=["ledger"])
def reconciliation(
    context: LedgerViewContext,
    db: DbSession,
) -> list[ReconciliationIssueOut]:
    rows = handle_read(lambda: ledger_services.reconciliation_issues(db, company_id(context)))
    return [ReconciliationIssueOut(**row) for row in rows]


@router.post(
    "/ledger/vendor-inventory/movements",
    response_model=VendorInventoryMovementOut,
    status_code=201,
    tags=["ledger"],
)
def vendor_inventory_movement_post(
    payload: VendorInventoryMovementCreate,
    context: VendorStockManageContext,
    db: DbSession,
) -> VendorInventoryMovementOut:
    try:
        row = ledger_services.record_vendor_inventory_movement(
            db,
            company_id=company_id(context),
            user_id=context.user.id,
            payload=payload,
        )
        db.commit()
        return inventory_movement_out(row)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


def admin_vendor(context: AuthContext, db: DbSession, vendor_id: str) -> Vendor:
    scoped = company_id(context)
    vendor = db.scalar(select(Vendor).where(Vendor.company_id == scoped, Vendor.id == vendor_id))
    if vendor is None:
        error = ServiceError(404, "Vendor not found.")
        raise service_error_to_http(error) from error
    return vendor


@router.get(
    "/ledger/vendors/{vendor_id}/overview", response_model=VendorLedgerOverviewOut, tags=["ledger"]
)
def admin_vendor_overview(
    vendor_id: str, context: LedgerViewContext, db: DbSession
) -> VendorLedgerOverviewOut:
    admin_vendor(context, db, vendor_id)
    return VendorLedgerOverviewOut(
        **ledger_services.vendor_overview(db, company_id(context), vendor_id)
    )


@router.get(
    "/ledger/vendors/{vendor_id}/ledger", response_model=list[VendorLedgerLineOut], tags=["ledger"]
)
def admin_vendor_ledger(
    vendor_id: str,
    context: LedgerViewContext,
    db: DbSession,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    offset: PageOffset = 0,
    limit: PageLimit = 100,
) -> list[VendorLedgerLineOut]:
    validate_date_range(date_from, date_to)
    admin_vendor(context, db, vendor_id)
    return [
        VendorLedgerLineOut(**row)
        for row in ledger_services.vendor_ledger_rows(
            db,
            company_id(context),
            vendor_id,
            date_from=date_from,
            date_to=date_to,
            offset=offset,
            limit=limit,
        )
    ]


@router.get(
    "/ledger/vendors/{vendor_id}/stock",
    response_model=list[VendorInventoryBalanceOut],
    tags=["ledger"],
)
def admin_vendor_stock(
    vendor_id: str,
    context: LedgerViewContext,
    db: DbSession,
    product_id: str | None = None,
    warehouse_id: str | None = None,
) -> list[VendorInventoryBalanceOut]:
    admin_vendor(context, db, vendor_id)
    return [
        inventory_balance_out(row)
        for row in ledger_services.list_vendor_inventory_balances(
            db,
            company_id(context),
            vendor_id,
            product_id=product_id,
            warehouse_id=warehouse_id,
        )
    ]


@router.get(
    "/ledger/vendors/{vendor_id}/stock/movements",
    response_model=list[VendorInventoryMovementOut],
    tags=["ledger"],
)
def admin_vendor_stock_movements(
    vendor_id: str,
    context: LedgerViewContext,
    db: DbSession,
    product_id: str | None = None,
    warehouse_id: str | None = None,
    movement_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    offset: PageOffset = 0,
    limit: PageLimit = 100,
) -> list[VendorInventoryMovementOut]:
    validate_date_range(date_from, date_to)
    admin_vendor(context, db, vendor_id)
    return [
        inventory_movement_out(row)
        for row in ledger_services.list_vendor_inventory_movements(
            db,
            company_id(context),
            vendor_id,
            product_id=product_id,
            warehouse_id=warehouse_id,
            movement_type=movement_type,
            date_from=date_from,
            date_to=date_to,
            offset=offset,
            limit=limit,
        )
    ]


def admin_vendor_order_rows(
    vendor_id: str,
    context: AuthContext,
    db: DbSession,
    *,
    status: str | None = None,
    order_status: str | None = None,
    payment_status: str | None = None,
    settlement_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    offset: int = 0,
    limit: int = 100,
) -> list[VendorOrderItemOut]:
    validate_date_range(date_from, date_to)
    admin_vendor(context, db, vendor_id)
    return [
        marketplace_services.vendor_order_item_out(row, db=db)
        for row in marketplace_services.list_vendor_order_items(
            db,
            company_id(context),
            vendor_id=vendor_id,
            status=status,
            order_status=order_status,
            payment_status=payment_status,
            settlement_id=settlement_id,
            date_from=date_from,
            date_to=date_to,
            offset=offset,
            limit=limit,
        )
    ]


@router.get(
    "/ledger/vendors/{vendor_id}/orders", response_model=list[VendorOrderItemOut], tags=["ledger"]
)
def admin_vendor_orders(
    vendor_id: str,
    context: LedgerViewContext,
    db: DbSession,
    status: str | None = None,
    order_status: str | None = None,
    payment_status: str | None = None,
    settlement_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    offset: PageOffset = 0,
    limit: PageLimit = 100,
) -> list[VendorOrderItemOut]:
    return admin_vendor_order_rows(
        vendor_id,
        context,
        db,
        status=status,
        order_status=order_status,
        payment_status=payment_status,
        settlement_id=settlement_id,
        date_from=date_from,
        date_to=date_to,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/ledger/vendors/{vendor_id}/sales", response_model=list[VendorOrderItemOut], tags=["ledger"]
)
@router.get(
    "/ledger/vendors/{vendor_id}/reports/sales",
    response_model=list[VendorOrderItemOut],
    tags=["ledger"],
)
def admin_vendor_sales(
    vendor_id: str,
    context: LedgerViewContext,
    db: DbSession,
    status: str | None = None,
    order_status: str | None = None,
    payment_status: str | None = None,
    settlement_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    offset: PageOffset = 0,
    limit: PageLimit = 100,
) -> list[VendorOrderItemOut]:
    return admin_vendor_order_rows(
        vendor_id,
        context,
        db,
        status=status,
        order_status=order_status,
        payment_status=payment_status,
        settlement_id=settlement_id,
        date_from=date_from,
        date_to=date_to,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/ledger/vendors/{vendor_id}/settlements",
    response_model=list[VendorSettlementOut],
    tags=["ledger"],
)
@router.get(
    "/ledger/vendors/{vendor_id}/reports/settlements",
    response_model=list[VendorSettlementOut],
    tags=["ledger"],
)
def admin_vendor_settlements(
    vendor_id: str,
    context: LedgerViewContext,
    db: DbSession,
    status: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    offset: PageOffset = 0,
    limit: PageLimit = 100,
) -> list[VendorSettlementOut]:
    validate_date_range(date_from, date_to)
    admin_vendor(context, db, vendor_id)
    return [
        marketplace_services.vendor_settlement_out(row)
        for row in marketplace_services.list_vendor_settlements(
            db,
            company_id(context),
            vendor_id=vendor_id,
            status=status,
            date_from=date_from,
            date_to=date_to,
            offset=offset,
            limit=limit,
        )
    ]


@router.get(
    "/ledger/vendors/{vendor_id}/reports/stock",
    response_model=list[VendorInventoryBalanceOut],
    tags=["ledger"],
)
def admin_vendor_stock_report(
    vendor_id: str, context: LedgerViewContext, db: DbSession
) -> list[VendorInventoryBalanceOut]:
    return admin_vendor_stock(vendor_id, context, db)


@router.get("/ledger/vendors/{vendor_id}/audit", response_model=list[AuditLogOut], tags=["ledger"])
def admin_vendor_audit(
    vendor_id: str,
    context: LedgerViewContext,
    db: DbSession,
    limit: PageLimit = 200,
) -> list[AuditLogOut]:
    admin_vendor(context, db, vendor_id)
    return [
        audit_out(row)
        for row in ledger_services.vendor_audit_rows(
            db, company_id(context), vendor_id, limit=limit
        )
    ]


@router.get("/vendor/ledger/overview", response_model=VendorLedgerOverviewOut, tags=["vendor"])
def own_ledger_overview(context: VendorLedgerContext, db: DbSession) -> VendorLedgerOverviewOut:
    vendor = own_vendor(db, context)
    return VendorLedgerOverviewOut(
        **ledger_services.vendor_overview(db, company_id(context), vendor.id)
    )


@router.get("/vendor/ledger/entries", response_model=list[VendorLedgerLineOut], tags=["vendor"])
def own_ledger_entries(
    context: VendorLedgerContext,
    db: DbSession,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    offset: PageOffset = 0,
    limit: PageLimit = 100,
) -> list[VendorLedgerLineOut]:
    validate_date_range(date_from, date_to)
    vendor = own_vendor(db, context)
    return [
        VendorLedgerLineOut(**row)
        for row in ledger_services.vendor_ledger_rows(
            db,
            company_id(context),
            vendor.id,
            date_from=date_from,
            date_to=date_to,
            offset=offset,
            limit=limit,
        )
    ]


@router.get(
    "/vendor/stock/overview", response_model=list[VendorInventoryBalanceOut], tags=["vendor"]
)
@router.get(
    "/vendor/reports/stock", response_model=list[VendorInventoryBalanceOut], tags=["vendor"]
)
def own_stock(
    context: VendorStockContext,
    db: DbSession,
    product_id: str | None = None,
    warehouse_id: str | None = None,
) -> list[VendorInventoryBalanceOut]:
    vendor = own_vendor(db, context)
    return [
        inventory_balance_out(row)
        for row in ledger_services.list_vendor_inventory_balances(
            db,
            company_id(context),
            vendor.id,
            product_id=product_id,
            warehouse_id=warehouse_id,
        )
    ]


@router.get(
    "/vendor/stock/movements", response_model=list[VendorInventoryMovementOut], tags=["vendor"]
)
def own_stock_movements(
    context: VendorStockContext,
    db: DbSession,
    product_id: str | None = None,
    warehouse_id: str | None = None,
    movement_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    offset: PageOffset = 0,
    limit: PageLimit = 100,
) -> list[VendorInventoryMovementOut]:
    validate_date_range(date_from, date_to)
    vendor = own_vendor(db, context)
    return [
        inventory_movement_out(row)
        for row in ledger_services.list_vendor_inventory_movements(
            db,
            company_id(context),
            vendor.id,
            product_id=product_id,
            warehouse_id=warehouse_id,
            movement_type=movement_type,
            date_from=date_from,
            date_to=date_to,
            offset=offset,
            limit=limit,
        )
    ]


@router.post(
    "/vendor/stock/movements",
    response_model=VendorInventoryMovementOut,
    status_code=201,
    tags=["vendor"],
)
def own_stock_movement_create(
    payload: VendorInventoryMovementCreate,
    context: VendorStockManageContext,
    db: DbSession,
) -> VendorInventoryMovementOut:
    """Record stock for the authenticated vendor only; never trust a supplied vendor ID."""
    try:
        vendor = own_vendor(db, context)
        row = ledger_services.record_vendor_inventory_movement(
            db,
            company_id=company_id(context),
            user_id=context.user.id,
            payload=payload.model_copy(update={"vendor_id": vendor.id}),
        )
        db.commit()
        return inventory_movement_out(row)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


def own_order_rows(
    context: AuthContext,
    db: DbSession,
    *,
    status: str | None = None,
    order_status: str | None = None,
    payment_status: str | None = None,
    settlement_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    offset: int = 0,
    limit: int = 100,
) -> list[VendorOrderItemOut]:
    validate_date_range(date_from, date_to)
    vendor = own_vendor(db, context)
    return [
        marketplace_services.vendor_order_item_out(row, db=db)
        for row in marketplace_services.list_vendor_order_items(
            db,
            company_id(context),
            vendor_id=vendor.id,
            status=status,
            order_status=order_status,
            payment_status=payment_status,
            settlement_id=settlement_id,
            date_from=date_from,
            date_to=date_to,
            offset=offset,
            limit=limit,
        )
    ]


@router.get("/vendor/sales", response_model=list[VendorOrderItemOut], tags=["vendor"])
@router.get("/vendor/reports/sales", response_model=list[VendorOrderItemOut], tags=["vendor"])
def own_sales(
    context: VendorReportsContext,
    db: DbSession,
    status: str | None = None,
    order_status: str | None = None,
    payment_status: str | None = None,
    settlement_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    offset: PageOffset = 0,
    limit: PageLimit = 100,
) -> list[VendorOrderItemOut]:
    return own_order_rows(
        context,
        db,
        status=status,
        order_status=order_status,
        payment_status=payment_status,
        settlement_id=settlement_id,
        date_from=date_from,
        date_to=date_to,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/vendor/reports/settlements", response_model=list[VendorSettlementOut], tags=["vendor"]
)
def own_settlement_report(
    context: VendorReportsContext,
    db: DbSession,
    status: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    offset: PageOffset = 0,
    limit: PageLimit = 100,
) -> list[VendorSettlementOut]:
    validate_date_range(date_from, date_to)
    vendor = own_vendor(db, context)
    return [
        marketplace_services.vendor_settlement_out(row)
        for row in marketplace_services.list_vendor_settlements(
            db,
            company_id(context),
            vendor_id=vendor.id,
            status=status,
            date_from=date_from,
            date_to=date_to,
            offset=offset,
            limit=limit,
        )
    ]


@router.get("/ledger/export/journals.csv", tags=["ledger"])
def journal_export(
    context: LedgerExportContext,
    db: DbSession,
    vendor_id: str | None = None,
    account_id: str | None = None,
    source_type: str | None = None,
    status: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> Response:
    validate_date_range(date_from, date_to)
    rows = ledger_services.list_journals(
        db,
        company_id(context),
        vendor_id=vendor_id,
        account_id=account_id,
        source_type=source_type,
        status=status,
        date_from=date_from,
        date_to=date_to,
        limit=500,
    )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["entry_number", "posted_at", "source_type", "source_id", "status", "memo"])
    for row in rows:
        writer.writerow(
            [row.entry_number, row.posted_at, row.source_type, row.source_id, row.status, row.memo]
        )
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=ledger-journals.csv"},
    )
