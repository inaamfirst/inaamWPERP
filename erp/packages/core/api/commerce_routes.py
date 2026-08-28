from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from erp.packages.core import commerce_services, ledger_services
from erp.packages.core.api.dependencies import (
    DbSession,
    require_any_permission,
    require_permission,
    service_error_to_http,
)
from erp.packages.core.api.serializers import order_out
from erp.packages.core.db.models import Product, ProductChannelListing, Warehouse
from erp.packages.core.inventory_services import record_stock_movement
from erp.packages.core.marketplace_services import vendor_for_user
from erp.packages.core.schemas import (
    OrderOut,
    PosSaleCreate,
    ProductChannelListingCreate,
    ProductChannelListingOut,
    StockMovementCreate,
    StockReservationCreate,
    StockReservationOut,
    SupportContactCreate,
    SupportContactOut,
)
from erp.packages.core.services import AuthContext, ServiceError

router = APIRouter()

AdminCommerceContext = Annotated[AuthContext, Depends(require_permission("catalog.manage"))]
AdminDashboardContext = Annotated[AuthContext, Depends(require_permission("reports.view"))]
VendorCommerceViewContext = Annotated[
    AuthContext, Depends(require_permission("vendor.products.view"))
]
VendorLedgerViewContext = Annotated[
    AuthContext, Depends(require_permission("vendor.ledger.view"))
]
VendorStockViewContext = Annotated[
    AuthContext, Depends(require_permission("vendor.stock.view"))
]
VendorSupportViewContext = Annotated[
    AuthContext, Depends(require_permission("vendor.profile.view"))
]
VendorWarehouseViewContext = Annotated[
    AuthContext,
    Depends(require_any_permission("vendor.stock.view", "vendor.orders.manage")),
]
VendorCommerceProductContext = Annotated[
    AuthContext, Depends(require_permission("vendor.products.manage"))
]
VendorCommerceStockContext = Annotated[
    AuthContext, Depends(require_permission("vendor.stock.manage"))
]
VendorCommerceOrderContext = Annotated[
    AuthContext, Depends(require_permission("vendor.orders.manage"))
]
SupportManageContext = Annotated[AuthContext, Depends(require_permission("settings.manage"))]


def _vendor_id(db, context: AuthContext) -> str:
    if not context.user.company_id:
        raise ServiceError(403, "A company-scoped user is required.")
    vendor = vendor_for_user(db, context.user.company_id, context.user.id)
    return vendor.id


def _listing_out(row: ProductChannelListing) -> ProductChannelListingOut:
    return ProductChannelListingOut(
        id=row.id,
        product_id=row.product_id,
        vendor_id=row.vendor_id,
        channel=row.channel,
        listing_status=row.listing_status,
        channel_sku=row.channel_sku,
        price_minor=row.price_minor,
        external_id=row.external_id,
        sync_status=row.sync_status,
        last_synced_at=row.last_synced_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _reservation_out(row) -> StockReservationOut:
    return StockReservationOut(
        id=row.id,
        warehouse_id=row.warehouse_id,
        product_id=row.product_id,
        variant_id=row.variant_id,
        source_type=row.source_type,
        source_id=row.source_id,
        quantity=row.quantity,
        status=row.status,
        idempotency_key=row.idempotency_key,
        released_at=row.released_at,
        created_at=row.created_at,
    )


@router.get("/commerce/dashboard", response_model=dict[str, object], tags=["commerce"])
def admin_dashboard(
    context: AdminDashboardContext,
    db: DbSession,
    workspace: str = Query(default="combined"),
) -> dict[str, object]:
    try:
        return commerce_services.dashboard_summary(db, context.user.company_id, workspace=workspace)
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.get("/commerce/vendor/dashboard", response_model=dict[str, object], tags=["commerce"])
def vendor_dashboard(
    context: VendorCommerceViewContext,
    db: DbSession,
    workspace: str = Query(default="combined"),
) -> dict[str, object]:
    try:
        return commerce_services.dashboard_summary(
            db, context.user.company_id, vendor_id=_vendor_id(db, context), workspace=workspace
        )
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.get(
    "/commerce/vendor/products/channels",
    response_model=list[ProductChannelListingOut],
    tags=["commerce"],
)
def vendor_channel_listings(
    context: VendorCommerceViewContext,
    db: DbSession,
) -> list[ProductChannelListingOut]:
    try:
        return [
            _listing_out(row)
            for row in commerce_services.list_channel_listings(
                db, context.user.company_id, vendor_id=_vendor_id(db, context)
            )
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.put(
    "/commerce/vendor/products/{product_id}/channel",
    response_model=ProductChannelListingOut,
    tags=["commerce"],
)
def vendor_channel_listing_update(
    product_id: str,
    payload: ProductChannelListingCreate,
    context: VendorCommerceProductContext,
    db: DbSession,
) -> ProductChannelListingOut:
    try:
        row = commerce_services.upsert_channel_listing(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            product_id=product_id,
            payload=payload,
            vendor_id=_vendor_id(db, context),
        )
        db.commit()
        return _listing_out(row)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get(
    "/commerce/admin/products/channels",
    response_model=list[ProductChannelListingOut],
    tags=["commerce"],
)
def admin_channel_listings(
    context: AdminCommerceContext, db: DbSession
) -> list[ProductChannelListingOut]:
    return [
        _listing_out(row)
        for row in commerce_services.list_channel_listings(db, context.user.company_id)
    ]


@router.put(
    "/commerce/admin/products/{product_id}/channel",
    response_model=ProductChannelListingOut,
    tags=["commerce"],
)
def admin_channel_listing_update(
    product_id: str,
    payload: ProductChannelListingCreate,
    context: AdminCommerceContext,
    db: DbSession,
) -> ProductChannelListingOut:
    try:
        row = commerce_services.upsert_channel_listing(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            product_id=product_id,
            payload=payload,
        )
        db.commit()
        return _listing_out(row)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get("/commerce/vendor/stock", response_model=list[dict[str, object]], tags=["commerce"])
def vendor_stock(context: VendorStockViewContext, db: DbSession) -> list[dict[str, object]]:
    try:
        return commerce_services.list_vendor_stock(
            db, context.user.company_id, _vendor_id(db, context)
        )
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.get("/commerce/vendor/ledger/overview", response_model=dict[str, object], tags=["commerce"])
def vendor_commerce_ledger(context: VendorLedgerViewContext, db: DbSession) -> dict[str, object]:
    try:
        return ledger_services.vendor_overview(
            db, context.user.company_id, _vendor_id(db, context)
        )
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.get(
    "/commerce/vendor/warehouses", response_model=list[dict[str, object]], tags=["commerce"]
)
def vendor_warehouses(
    context: VendorWarehouseViewContext, db: DbSession
) -> list[dict[str, object]]:
    if not context.user.company_id:
        raise service_error_to_http(ServiceError(403, "A company-scoped user is required."))
    rows = db.scalars(
        select(Warehouse)
        .where(Warehouse.company_id == context.user.company_id, Warehouse.is_active.is_(True))
        .order_by(Warehouse.code)
    ).all()
    return [{"id": row.id, "code": row.code, "name": row.name} for row in rows]


@router.post(
    "/commerce/vendor/stock/movements", response_model=dict[str, object], tags=["commerce"]
)
def vendor_stock_movement(
    payload: StockMovementCreate,
    context: VendorCommerceStockContext,
    db: DbSession,
) -> dict[str, object]:
    try:
        vendor_id = _vendor_id(db, context)
        product = db.scalar(
            select(Product).where(
                Product.company_id == context.user.company_id,
                Product.id == payload.product_id,
                Product.vendor_id == vendor_id,
            )
        )
        if product is None:
            raise ServiceError(403, "Product is outside the vendor scope.")
        movement = record_stock_movement(
            db, company_id=context.user.company_id, user_id=context.user.id, payload=payload
        )
        db.commit()
        return {
            "id": movement.id,
            "product_id": movement.product_id,
            "quantity_delta": movement.quantity_delta,
        }
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.post(
    "/commerce/vendor/pos/sales", response_model=OrderOut, status_code=201, tags=["commerce"]
)
def vendor_pos_sale(
    payload: PosSaleCreate,
    context: VendorCommerceOrderContext,
    db: DbSession,
) -> OrderOut:
    try:
        order = commerce_services.create_pos_sale(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            vendor_id=_vendor_id(db, context),
            payload=payload,
        )
        db.commit()
        return order_out(db, order)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.post(
    "/commerce/admin/pos/sales", response_model=OrderOut, status_code=201, tags=["commerce"]
)
def admin_pos_sale(
    payload: PosSaleCreate, context: AdminCommerceContext, db: DbSession
) -> OrderOut:
    try:
        order = commerce_services.create_pos_sale(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            vendor_id=None,
            payload=payload,
        )
        db.commit()
        return order_out(db, order)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.post(
    "/commerce/stock/reservations",
    response_model=StockReservationOut,
    status_code=201,
    tags=["commerce"],
)
def stock_reservation(
    payload: StockReservationCreate,
    context: AdminCommerceContext,
    db: DbSession,
) -> StockReservationOut:
    try:
        row = commerce_services.reserve_stock(
            db, company_id=context.user.company_id, user_id=context.user.id, payload=payload
        )
        db.commit()
        return _reservation_out(row)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get("/commerce/support/contacts", response_model=list[SupportContactOut], tags=["commerce"])
def support_contacts(context: VendorSupportViewContext, db: DbSession) -> list[SupportContactOut]:
    return [
        SupportContactOut(**commerce_services.support_contact_out(row))
        for row in commerce_services.list_support_contacts(db, context.user.company_id)
    ]


@router.get(
    "/commerce/admin/support/contacts", response_model=list[SupportContactOut], tags=["commerce"]
)
def admin_support_contacts(context: SupportManageContext, db: DbSession) -> list[SupportContactOut]:
    return [
        SupportContactOut(**commerce_services.support_contact_out(row))
        for row in commerce_services.list_support_contacts(
            db, context.user.company_id, include_inactive=True
        )
    ]


@router.post(
    "/commerce/admin/support/contacts",
    response_model=SupportContactOut,
    status_code=201,
    tags=["commerce"],
)
def admin_support_contact_create(
    payload: SupportContactCreate, context: SupportManageContext, db: DbSession
) -> SupportContactOut:
    try:
        row = commerce_services.create_support_contact(
            db, company_id=context.user.company_id, user_id=context.user.id, payload=payload
        )
        db.commit()
        return SupportContactOut(**commerce_services.support_contact_out(row))
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.put(
    "/commerce/admin/support/contacts/{contact_id}",
    response_model=SupportContactOut,
    tags=["commerce"],
)
def admin_support_contact_update(
    contact_id: str, payload: SupportContactCreate, context: SupportManageContext, db: DbSession
) -> SupportContactOut:
    try:
        row = commerce_services.update_support_contact(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            contact_id=contact_id,
            payload=payload,
        )
        db.commit()
        return SupportContactOut(**commerce_services.support_contact_out(row))
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc
