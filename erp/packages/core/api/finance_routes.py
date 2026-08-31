from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from erp.packages.core import finance_services, marketplace_services
from erp.packages.core.api.dependencies import DbSession, require_permission, service_error_to_http
from erp.packages.core.schemas import (
    CODCollectionCreate,
    CODCollectionOut,
    CODReconciliationRequest,
    FinanceDashboardOut,
    RiderAdjustmentCreate,
    RiderCashRemittanceOut,
    RiderFinanceProfileOut,
    RiderFinanceProfileUpdate,
    RiderLedgerEntryOut,
    RiderPayoutCreate,
    RiderPayoutOut,
    RiderRemittanceCreate,
    RiderRemittanceReconciliationRequest,
    VendorFinanceDecision,
    VendorOrderItemOut,
)
from erp.packages.core.services import AuthContext, ServiceError, user_role_names

router = APIRouter()

FinanceViewContext = Annotated[AuthContext, Depends(require_permission("accounting.view"))]
FinancePostContext = Annotated[AuthContext, Depends(require_permission("accounting.post"))]
FinanceReconcileContext = Annotated[
    AuthContext, Depends(require_permission("accounting.reconcile"))
]
VendorSettleContext = Annotated[AuthContext, Depends(require_permission("vendors.settle"))]
RiderFinanceViewContext = Annotated[AuthContext, Depends(require_permission("rider.finance.view"))]
RiderFinanceSubmitContext = Annotated[
    AuthContext, Depends(require_permission("rider.finance.submit"))
]


def _company_id(context: AuthContext) -> str:
    if not context.user.company_id:
        raise ServiceError(403, "A company-scoped user is required.")
    return context.user.company_id


def _current_rider(context: AuthContext, db: DbSession) -> str:
    if "Rider" not in user_role_names(db, context.user.id):
        raise ServiceError(403, "A Rider role is required for financial access.")
    return context.user.id


@router.get("/finance/dashboard", response_model=FinanceDashboardOut, tags=["finance"])
def admin_finance_dashboard(
    context: FinanceViewContext,
    db: DbSession,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> FinanceDashboardOut:
    try:
        return FinanceDashboardOut(
            **finance_services.finance_dashboard(
                db,
                _company_id(context),
                date_from=date_from,
                date_to=date_to,
            )
        )
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.get("/finance/cod-collections", response_model=list[CODCollectionOut], tags=["finance"])
def admin_cod_collections(
    context: FinanceViewContext,
    db: DbSession,
    rider_user_id: str | None = None,
    status: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[CODCollectionOut]:
    return [
        CODCollectionOut(**finance_services._collection_out(db, row))
        for row in finance_services.list_collections(
            db,
            _company_id(context),
            rider_user_id=rider_user_id,
            status=status,
            date_from=date_from,
            date_to=date_to,
        )
    ]


@router.post(
    "/finance/cod-collections/{collection_id}/reconcile",
    response_model=CODCollectionOut,
    tags=["finance"],
)
def admin_cod_reconcile(
    collection_id: str,
    payload: CODReconciliationRequest,
    context: FinanceReconcileContext,
    db: DbSession,
) -> CODCollectionOut:
    try:
        row = finance_services.reconcile_cod_collection(
            db,
            company_id=_company_id(context),
            actor_user_id=context.user.id,
            collection_id=collection_id,
            payload=payload,
        )
        db.commit()
        return CODCollectionOut(**finance_services._collection_out(db, row))
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get("/finance/remittances", response_model=list[RiderCashRemittanceOut], tags=["finance"])
def admin_remittances(
    context: FinanceViewContext,
    db: DbSession,
    rider_user_id: str | None = None,
    status: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[RiderCashRemittanceOut]:
    return [
        RiderCashRemittanceOut(**finance_services._remittance_out(db, row))
        for row in finance_services.list_remittances(
            db,
            _company_id(context),
            rider_user_id=rider_user_id,
            status=status,
            date_from=date_from,
            date_to=date_to,
        )
    ]


@router.post(
    "/finance/remittances/{remittance_id}/reconcile",
    response_model=RiderCashRemittanceOut,
    tags=["finance"],
)
def admin_remittance_reconcile(
    remittance_id: str,
    payload: RiderRemittanceReconciliationRequest,
    context: FinanceReconcileContext,
    db: DbSession,
) -> RiderCashRemittanceOut:
    try:
        row = finance_services.reconcile_remittance(
            db,
            company_id=_company_id(context),
            actor_user_id=context.user.id,
            remittance_id=remittance_id,
            payload=payload,
        )
        db.commit()
        return RiderCashRemittanceOut(**finance_services._remittance_out(db, row))
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get(
    "/finance/riders/profiles", response_model=list[RiderFinanceProfileOut], tags=["finance"]
)
def admin_rider_profiles(
    context: FinanceViewContext, db: DbSession
) -> list[RiderFinanceProfileOut]:
    return [
        RiderFinanceProfileOut(**finance_services.profile_out(row))
        for row in finance_services.list_rider_profiles(db, _company_id(context))
    ]


@router.get(
    "/finance/riders/{rider_user_id}/profile",
    response_model=RiderFinanceProfileOut,
    tags=["finance"],
)
def admin_rider_profile(
    rider_user_id: str, context: FinanceViewContext, db: DbSession
) -> RiderFinanceProfileOut:
    row = finance_services.get_rider_profile(db, _company_id(context), rider_user_id)
    if row is None:
        raise service_error_to_http(ServiceError(404, "Rider fee profile not configured."))
    return RiderFinanceProfileOut(**finance_services.profile_out(row))


@router.put(
    "/finance/riders/{rider_user_id}/profile",
    response_model=RiderFinanceProfileOut,
    tags=["finance"],
)
def admin_rider_profile_save(
    rider_user_id: str,
    payload: RiderFinanceProfileUpdate,
    context: FinancePostContext,
    db: DbSession,
) -> RiderFinanceProfileOut:
    try:
        row = finance_services.set_rider_profile(
            db,
            company_id=_company_id(context),
            actor_user_id=context.user.id,
            rider_user_id=rider_user_id,
            payload=payload,
        )
        db.commit()
        return RiderFinanceProfileOut(**finance_services.profile_out(row))
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get("/finance/riders/{rider_user_id}/summary", tags=["finance"])
def admin_rider_summary(
    rider_user_id: str, context: FinanceViewContext, db: DbSession
) -> dict[str, int]:
    return finance_services.rider_summary(db, _company_id(context), rider_user_id)


@router.get(
    "/finance/riders/{rider_user_id}/ledger",
    response_model=list[RiderLedgerEntryOut],
    tags=["finance"],
)
def admin_rider_ledger(
    rider_user_id: str, context: FinanceViewContext, db: DbSession
) -> list[RiderLedgerEntryOut]:
    return [
        RiderLedgerEntryOut(**finance_services.ledger_entry_out(row))
        for row in finance_services.list_rider_ledger_entries(
            db, _company_id(context), rider_user_id
        )
    ]


@router.post(
    "/finance/riders/{rider_user_id}/adjustments",
    response_model=RiderLedgerEntryOut,
    tags=["finance"],
)
def admin_rider_adjustment(
    rider_user_id: str,
    payload: RiderAdjustmentCreate,
    context: FinancePostContext,
    db: DbSession,
) -> RiderLedgerEntryOut:
    try:
        row = finance_services.post_rider_adjustment(
            db,
            company_id=_company_id(context),
            actor_user_id=context.user.id,
            rider_user_id=rider_user_id,
            payload=payload,
        )
        db.commit()
        return RiderLedgerEntryOut(**finance_services.ledger_entry_out(row))
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get(
    "/finance/riders/{rider_user_id}/payouts", response_model=list[RiderPayoutOut], tags=["finance"]
)
def admin_rider_payouts(
    rider_user_id: str, context: FinanceViewContext, db: DbSession
) -> list[RiderPayoutOut]:
    return [
        RiderPayoutOut(**finance_services.payout_out(row))
        for row in finance_services.list_rider_payouts(db, _company_id(context), rider_user_id)
    ]


@router.post(
    "/finance/riders/{rider_user_id}/payouts", response_model=RiderPayoutOut, tags=["finance"]
)
def admin_rider_payout(
    rider_user_id: str,
    payload: RiderPayoutCreate,
    context: FinancePostContext,
    db: DbSession,
) -> RiderPayoutOut:
    try:
        row = finance_services.create_rider_payout(
            db,
            company_id=_company_id(context),
            actor_user_id=context.user.id,
            rider_user_id=rider_user_id,
            payload=payload,
        )
        db.commit()
        return RiderPayoutOut(**finance_services.payout_out(row))
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.post(
    "/finance/vendor-order-items/{vendor_order_item_id}/decision",
    response_model=VendorOrderItemOut,
    tags=["finance"],
)
def admin_vendor_finance_decision(
    vendor_order_item_id: str,
    payload: VendorFinanceDecision,
    context: VendorSettleContext,
    db: DbSession,
) -> VendorOrderItemOut:
    try:
        row = finance_services.decide_vendor_item(
            db,
            company_id=_company_id(context),
            actor_user_id=context.user.id,
            vendor_order_item_id=vendor_order_item_id,
            payload=payload,
        )
        db.commit()
        return marketplace_services.vendor_order_item_out(row, db=db)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get("/finance/vendor-sales", response_model=list[VendorOrderItemOut], tags=["finance"])
def admin_vendor_sales(
    context: FinanceViewContext,
    db: DbSession,
    finance_status: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[VendorOrderItemOut]:
    try:
        rows = marketplace_services.list_vendor_order_items(
            db,
            _company_id(context),
            date_from=date_from,
            date_to=date_to,
        )
        if finance_status:
            rows = [row for row in rows if row.finance_status == finance_status]
        return [marketplace_services.vendor_order_item_out(row, db=db) for row in rows]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.get("/rider/finance/summary", tags=["rider-finance"])
def rider_finance_summary(context: RiderFinanceViewContext, db: DbSession) -> dict[str, int]:
    try:
        return finance_services.rider_summary(db, _company_id(context), _current_rider(context, db))
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.get(
    "/rider/finance/cod-collections", response_model=list[CODCollectionOut], tags=["rider-finance"]
)
def rider_cod_collections(
    context: RiderFinanceViewContext, db: DbSession, status: str | None = Query(default=None)
) -> list[CODCollectionOut]:
    try:
        rider_id = _current_rider(context, db)
        return [
            CODCollectionOut(**finance_services._collection_out(db, row))
            for row in finance_services.list_collections(
                db, _company_id(context), rider_user_id=rider_id, status=status
            )
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.post(
    "/rider/finance/cod-collections",
    response_model=CODCollectionOut,
    status_code=201,
    tags=["rider-finance"],
)
def rider_cod_collection_submit(
    payload: CODCollectionCreate, context: RiderFinanceSubmitContext, db: DbSession
) -> CODCollectionOut:
    try:
        row = finance_services.submit_cod_collection(
            db,
            company_id=_company_id(context),
            rider_user_id=_current_rider(context, db),
            payload=payload,
        )
        db.commit()
        return CODCollectionOut(**finance_services._collection_out(db, row))
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get(
    "/rider/finance/remittances",
    response_model=list[RiderCashRemittanceOut],
    tags=["rider-finance"],
)
def rider_remittances(
    context: RiderFinanceViewContext, db: DbSession, status: str | None = Query(default=None)
) -> list[RiderCashRemittanceOut]:
    try:
        rider_id = _current_rider(context, db)
        return [
            RiderCashRemittanceOut(**finance_services._remittance_out(db, row))
            for row in finance_services.list_remittances(
                db, _company_id(context), rider_user_id=rider_id, status=status
            )
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.post(
    "/rider/finance/remittances",
    response_model=RiderCashRemittanceOut,
    status_code=201,
    tags=["rider-finance"],
)
def rider_remittance_submit(
    payload: RiderRemittanceCreate, context: RiderFinanceSubmitContext, db: DbSession
) -> RiderCashRemittanceOut:
    try:
        row = finance_services.submit_remittance(
            db,
            company_id=_company_id(context),
            rider_user_id=_current_rider(context, db),
            payload=payload,
        )
        db.commit()
        return RiderCashRemittanceOut(**finance_services._remittance_out(db, row))
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get(
    "/rider/finance/ledger", response_model=list[RiderLedgerEntryOut], tags=["rider-finance"]
)
def rider_ledger(context: RiderFinanceViewContext, db: DbSession) -> list[RiderLedgerEntryOut]:
    try:
        rider_id = _current_rider(context, db)
        return [
            RiderLedgerEntryOut(**finance_services.ledger_entry_out(row))
            for row in finance_services.list_rider_ledger_entries(
                db, _company_id(context), rider_id
            )
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.get("/rider/finance/payouts", response_model=list[RiderPayoutOut], tags=["rider-finance"])
def rider_payouts(context: RiderFinanceViewContext, db: DbSession) -> list[RiderPayoutOut]:
    try:
        rider_id = _current_rider(context, db)
        return [
            RiderPayoutOut(**finance_services.payout_out(row))
            for row in finance_services.list_rider_payouts(db, _company_id(context), rider_id)
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc
