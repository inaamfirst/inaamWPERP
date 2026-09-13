from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from erp.packages.core import commerce_services, ledger_services, shop_services
from erp.packages.core.api.dependencies import (
    DbSession,
    require_any_permission,
    require_permission,
    service_error_to_http,
)
from erp.packages.core.api.serializers import order_out
from erp.packages.core.db.models import Order, Product, ProductChannelListing, VendorOrderItem, Warehouse
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
    ShopPublicationBulkUpdate,
    ShopPurchaseCreate,
    ShopPurchasePaymentCreate,
    ShopStockInCreate,
    ShopSupplierCreate,
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
VendorShopPurchaseContext = Annotated[
    AuthContext, Depends(require_permission("vendor.shop.purchases.manage"))
]
VendorShopAccountingContext = Annotated[
    AuthContext, Depends(require_permission("vendor.shop.accounting.view"))
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


def _supplier_out(row, *, outstanding_minor: int = 0) -> dict[str, object]:
    return {"id": row.id, "name": row.name, "contact_name": row.contact_name, "email": row.email,
            "phone": row.phone, "address": row.address, "is_active": row.is_active,
            "outstanding_minor": outstanding_minor}


def _purchase_out(row) -> dict[str, object]:
    return {"id": row.id, "purchase_number": row.purchase_number, "supplier_id": row.supplier_id,
            "warehouse_id": row.warehouse_id, "status": row.status, "payment_status": row.payment_status,
            "total_minor": row.total_minor, "paid_minor": row.paid_minor, "currency": row.currency,
            "notes": row.notes, "created_at": row.created_at}


@router.put("/commerce/vendor/products/channels/bulk", response_model=list[ProductChannelListingOut], tags=["commerce"])
def vendor_channel_listing_bulk_update(
    payload: ShopPublicationBulkUpdate, context: VendorCommerceProductContext, db: DbSession
) -> list[ProductChannelListingOut]:
    try:
        vendor_id = _vendor_id(db, context)
        rows = []
        for product_id in payload.product_ids:
            rows.append(commerce_services.upsert_channel_listing(
                db, company_id=context.user.company_id, user_id=context.user.id, product_id=product_id,
                payload=ProductChannelListingCreate(listing_status=payload.listing_status), vendor_id=vendor_id,
            ))
        db.commit()
        return [_listing_out(row) for row in rows]
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get("/commerce/vendor/shop/suppliers", tags=["commerce"])
def vendor_shop_suppliers(context: VendorShopPurchaseContext, db: DbSession) -> list[dict[str, object]]:
    vendor_id = _vendor_id(db, context)
    return [
        _supplier_out(
            row,
            outstanding_minor=shop_services.supplier_outstanding(
                db, context.user.company_id, vendor_id, row.id
            ),
        )
        for row in shop_services.list_suppliers(db, context.user.company_id, vendor_id)
    ]


@router.post("/commerce/vendor/shop/suppliers", status_code=201, tags=["commerce"])
def vendor_shop_supplier_create(payload: ShopSupplierCreate, context: VendorShopPurchaseContext, db: DbSession) -> dict[str, object]:
    try:
        row = shop_services.create_supplier(db, company_id=context.user.company_id, vendor_id=_vendor_id(db, context), user_id=context.user.id, payload=payload)
        db.commit()
        return _supplier_out(row)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.patch("/commerce/vendor/shop/suppliers/{supplier_id}", tags=["commerce"])
def vendor_shop_supplier_update(
    supplier_id: str, payload: ShopSupplierCreate, context: VendorShopPurchaseContext, db: DbSession
) -> dict[str, object]:
    try:
        row = shop_services.update_supplier(
            db, company_id=context.user.company_id, vendor_id=_vendor_id(db, context),
            user_id=context.user.id, supplier_id=supplier_id, payload=payload,
        )
        db.commit()
        return _supplier_out(row)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get("/commerce/vendor/shop/catalog", tags=["commerce"])
def vendor_shop_catalog(context: VendorWarehouseViewContext, db: DbSession) -> list[dict[str, object]]:
    try:
        rows = shop_services.list_shop_catalog(db, context.user.company_id, _vendor_id(db, context))
        # The first catalog visit provisions the vendor's dedicated shop location.
        db.commit()
        return rows
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.post("/commerce/vendor/shop/stock-in", status_code=201, tags=["commerce"])
def vendor_shop_stock_in(
    payload: ShopStockInCreate, context: VendorShopPurchaseContext, db: DbSession
) -> dict[str, object]:
    try:
        vendor_id = _vendor_id(db, context)
        warehouse = shop_services.vendor_shop_warehouse(db, context.user.company_id, vendor_id)
        product = db.scalar(select(Product).where(
            Product.company_id == context.user.company_id,
            Product.id == payload.product_id,
        ))
        if product is None or not shop_services.vendor_owns_product(
            db, context.user.company_id, vendor_id, product
        ):
            raise ServiceError(403, "Product is outside the vendor shop.")
        movement = record_stock_movement(
            db, company_id=context.user.company_id, user_id=context.user.id,
            payload=StockMovementCreate(
                movement_type="stock_in", warehouse_id=warehouse.id,
                product_id=product.id, quantity=payload.quantity,
                reference_type="shop_opening_stock", reference_id=product.id,
                reason=payload.reason or "Opening shop stock.",
            ),
        )
        quantity = shop_services.sync_product_catalog_quantity_from_shop(
            db,
            company_id=context.user.company_id,
            vendor_id=vendor_id,
            product_id=product.id,
        )
        db.commit()
        return {"id": movement.id, "product_id": product.id, "quantity": payload.quantity, "quantity_on_hand": quantity, "warehouse_id": warehouse.id}
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get("/commerce/vendor/shop/purchases", tags=["commerce"])
def vendor_shop_purchase_list(context: VendorShopPurchaseContext, db: DbSession) -> list[dict[str, object]]:
    return [_purchase_out(row) for row in shop_services.list_purchases(db, context.user.company_id, _vendor_id(db, context))]


@router.get("/commerce/vendor/shop/purchases/{purchase_id}", tags=["commerce"])
def vendor_shop_purchase_detail(purchase_id: str, context: VendorShopPurchaseContext, db: DbSession) -> dict[str, object]:
    detail = shop_services.purchase_detail(db, context.user.company_id, _vendor_id(db, context), purchase_id)
    purchase = detail["purchase"]
    return {
        "purchase": _purchase_out(purchase),
        "lines": [
            {"id": line.id, "product_id": line.product_id, "variant_id": line.variant_id,
             "quantity": line.quantity, "unit_cost_minor": line.unit_cost_minor,
             "line_total_minor": line.line_total_minor}
            for line in detail["lines"]
        ],
    }


@router.get("/commerce/vendor/shop/sales", tags=["commerce"])
def vendor_shop_sales(context: VendorCommerceOrderContext, db: DbSession) -> list[dict[str, object]]:
    return shop_services.list_recent_sales(db, context.user.company_id, _vendor_id(db, context))


@router.get("/commerce/vendor/shop/sales/{order_id}", response_model=OrderOut, tags=["commerce"])
def vendor_shop_sale_detail(order_id: str, context: VendorCommerceOrderContext, db: DbSession) -> OrderOut:
    vendor_id = _vendor_id(db, context)
    order = db.scalar(select(Order).join(VendorOrderItem, VendorOrderItem.order_id == Order.id).where(
        Order.company_id == context.user.company_id, Order.id == order_id,
        Order.sales_channel == "pos", VendorOrderItem.vendor_id == vendor_id,
    ))
    if order is None:
        raise service_error_to_http(ServiceError(404, "Shop sale not found."))
    return order_out(db, order)


@router.post("/commerce/vendor/shop/purchases", status_code=201, tags=["commerce"])
def vendor_shop_purchase_create(payload: ShopPurchaseCreate, context: VendorShopPurchaseContext, db: DbSession) -> dict[str, object]:
    try:
        row = shop_services.create_purchase(db, company_id=context.user.company_id, vendor_id=_vendor_id(db, context), user_id=context.user.id, payload=payload)
        db.commit()
        return _purchase_out(row)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.post("/commerce/vendor/shop/purchases/{purchase_id}/payments", tags=["commerce"])
def vendor_shop_purchase_payment(purchase_id: str, payload: ShopPurchasePaymentCreate, context: VendorShopPurchaseContext, db: DbSession) -> dict[str, object]:
    try:
        row = shop_services.pay_purchase(db, company_id=context.user.company_id, vendor_id=_vendor_id(db, context), user_id=context.user.id, purchase_id=purchase_id, payload=payload)
        db.commit()
        return _purchase_out(row)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get("/commerce/vendor/shop/accounting", tags=["commerce"])
def vendor_shop_accounting(context: VendorShopAccountingContext, db: DbSession) -> dict[str, object]:
    return shop_services.overview(db, context.user.company_id, _vendor_id(db, context))


@router.get("/commerce/admin/vendors/{vendor_id}/shop", tags=["commerce"])
def admin_vendor_shop(vendor_id: str, context: AdminCommerceContext, db: DbSession) -> dict[str, object]:
    warehouse = shop_services.vendor_shop_warehouse(db, context.user.company_id, vendor_id)
    db.commit()
    return {
        "warehouse": {"id": warehouse.id, "code": warehouse.code, "name": warehouse.name},
        "accounting": shop_services.overview(db, context.user.company_id, vendor_id),
        "suppliers": [
            _supplier_out(
                row,
                outstanding_minor=shop_services.supplier_outstanding(
                    db, context.user.company_id, vendor_id, row.id
                ),
            )
            for row in shop_services.list_suppliers(db, context.user.company_id, vendor_id)
        ],
        "catalog": shop_services.list_shop_catalog(db, context.user.company_id, vendor_id),
        "purchases": [_purchase_out(row) for row in shop_services.list_purchases(db, context.user.company_id, vendor_id)],
        "sales": shop_services.list_recent_sales(
            db, context.user.company_id, vendor_id, sales_channel=None
        ),
        "stock": commerce_services.list_vendor_stock(db, context.user.company_id, vendor_id),
    }

@router.get("/commerce/vendor/stock", response_model=list[dict[str, object]], tags=["commerce"])
def vendor_stock(context: VendorStockViewContext, db: DbSession) -> list[dict[str, object]]:
    try:
        rows = commerce_services.list_vendor_stock(
            db, context.user.company_id, _vendor_id(db, context)
        )
        db.commit()
        return rows
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
    shop_services.vendor_shop_warehouse(db, context.user.company_id, _vendor_id(db, context))
    rows = db.scalars(
        select(Warehouse)
        .where(
            Warehouse.company_id == context.user.company_id,
            Warehouse.vendor_id == _vendor_id(db, context),
            Warehouse.warehouse_type == "vendor_shop",
            Warehouse.is_active.is_(True),
        )
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
        shop_warehouse = shop_services.vendor_shop_warehouse(
            db, context.user.company_id, vendor_id
        )
        if payload.warehouse_id != shop_warehouse.id:
            raise ServiceError(
                403,
                "Vendor stock adjustments must use this vendor's Vendor Shop warehouse.",
            )
        product = db.scalar(
            select(Product).where(
                Product.company_id == context.user.company_id,
                Product.id == payload.product_id,
            )
        )
        if product is None or not shop_services.vendor_owns_product(
            db, context.user.company_id, vendor_id, product
        ):
            raise ServiceError(403, "Product is outside the vendor scope.")
        movement = record_stock_movement(
            db, company_id=context.user.company_id, user_id=context.user.id, payload=payload
        )
        quantity = shop_services.sync_product_catalog_quantity_from_shop(
            db,
            company_id=context.user.company_id,
            vendor_id=vendor_id,
            product_id=product.id,
        )
        db.commit()
        return {
            "id": movement.id,
            "product_id": movement.product_id,
            "quantity_delta": movement.quantity_delta,
            "warehouse_id": movement.warehouse_id,
            "quantity_on_hand": quantity,
            "stock_quantity": product.stock_quantity,
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
