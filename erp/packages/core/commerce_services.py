from __future__ import annotations

from urllib.parse import quote

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from erp.packages.core.catalog_services import get_product, require_company_id
from erp.packages.core.customer_services import create_customer
from erp.packages.core.db.models import (
    Order,
    OrderStatusHistory,
    Product,
    ProductChannelListing,
    StockReservation,
    SupportContact,
    VendorOrderItem,
    Warehouse,
    ShopFinanceEntry,
)
from erp.packages.core.inventory_services import current_stock, get_warehouse, record_stock_movement
from erp.packages.core.order_services import create_order, order_items, record_payment
from erp.packages.core.schemas import (
    CustomerCreate,
    OrderCreate,
    OrderItemCreate,
    PosSaleCreate,
    ProductChannelListingCreate,
    StockMovementCreate,
    StockReservationCreate,
    SupportContactCreate,
)
from erp.packages.core.services import ServiceError, record_audit

LISTING_STATUSES = {"private", "draft", "published", "paused"}


def _company(company_id: str | None) -> str:
    return require_company_id(company_id)


def _vendor_product_ids(db: Session, company_id: str, vendor_id: str) -> set[str]:
    rows = db.scalars(
        select(Product.id).where(Product.company_id == company_id, Product.vendor_id == vendor_id)
    ).all()
    return set(rows)


def list_channel_listings(
    db: Session,
    company_id: str | None,
    *,
    vendor_id: str | None = None,
    channel: str = "woocommerce",
) -> list[ProductChannelListing]:
    scoped = _company(company_id)
    query = select(ProductChannelListing).where(
        ProductChannelListing.company_id == scoped,
        ProductChannelListing.channel == channel,
    )
    if vendor_id:
        query = query.where(ProductChannelListing.vendor_id == vendor_id)
    return list(db.scalars(query.order_by(ProductChannelListing.updated_at.desc())).all())


def upsert_channel_listing(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    product_id: str,
    payload: ProductChannelListingCreate,
    vendor_id: str | None = None,
) -> ProductChannelListing:
    scoped = _company(company_id)
    product = get_product(db, scoped, product_id)
    if vendor_id and product.id not in _vendor_product_ids(db, scoped, vendor_id):
        raise ServiceError(403, "Product is outside the vendor scope.")
    listing = db.scalar(
        select(ProductChannelListing).where(
            ProductChannelListing.company_id == scoped,
            ProductChannelListing.product_id == product.id,
            ProductChannelListing.channel == payload.channel,
        )
    )
    if listing is None:
        listing = ProductChannelListing(
            company_id=scoped,
            product_id=product.id,
            vendor_id=vendor_id or product.vendor_id,
            channel=payload.channel,
        )
        db.add(listing)
    elif vendor_id and listing.vendor_id != vendor_id:
        raise ServiceError(403, "Channel listing is outside the vendor scope.")
    listing.listing_status = payload.listing_status
    listing.channel_sku = payload.channel_sku or product.sku
    listing.price_minor = payload.price_minor
    listing.sync_status = "pending" if payload.listing_status == "published" else "not_required"
    db.flush()
    # Listing changes are explicit online-publication actions. Queue both publish
    # and unpublish updates so an already mapped remote product is hidden.
    from erp.packages.core.woocommerce_services import enqueue_product_sync

    try:
        enqueue_product_sync(db, company_id=scoped, product=product)
    except ServiceError as exc:
        if exc.status_code != 404 or exc.message != "WooCommerce is not configured.":
            raise
    record_audit(
        db,
        action="commerce.product_channel_listing_updated",
        company_id=scoped,
        user_id=user_id,
        entity_type="product_channel_listing",
        entity_id=listing.id,
        metadata={
            "product_id": product.id,
            "channel": payload.channel,
            "status": listing.listing_status,
        },
    )
    return listing


def support_contact_out(contact: SupportContact) -> dict[str, object]:
    phone = "".join(ch for ch in contact.phone if ch.isdigit())
    message = quote(contact.whatsapp_message or "", safe="")
    url = f"https://wa.me/{phone}"
    if message:
        url += f"?text={message}"
    return {
        "id": contact.id,
        "label": contact.label,
        "role": contact.role,
        "phone": contact.phone,
        "whatsapp_url": url,
        "whatsapp_message": contact.whatsapp_message,
        "working_hours": contact.working_hours,
        "priority": contact.priority,
        "is_active": contact.is_active,
        "created_at": contact.created_at,
        "updated_at": contact.updated_at,
    }


def list_support_contacts(db: Session, company_id: str | None, *, include_inactive: bool = False):
    scoped = _company(company_id)
    query = select(SupportContact).where(SupportContact.company_id == scoped)
    if not include_inactive:
        query = query.where(SupportContact.is_active.is_(True))
    return list(db.scalars(query.order_by(SupportContact.priority, SupportContact.label)).all())


def create_support_contact(
    db: Session, *, company_id: str | None, user_id: str, payload: SupportContactCreate
) -> SupportContact:
    scoped = _company(company_id)
    contact = SupportContact(company_id=scoped, **payload.model_dump())
    db.add(contact)
    db.flush()
    record_audit(
        db,
        action="commerce.support_contact_created",
        company_id=scoped,
        user_id=user_id,
        entity_type="support_contact",
        entity_id=contact.id,
    )
    return contact


def update_support_contact(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    contact_id: str,
    payload: SupportContactCreate,
) -> SupportContact:
    scoped = _company(company_id)
    contact = db.scalar(
        select(SupportContact).where(
            SupportContact.company_id == scoped, SupportContact.id == contact_id
        )
    )
    if contact is None:
        raise ServiceError(404, "Support contact not found.")
    for field, value in payload.model_dump().items():
        setattr(contact, field, value)
    db.flush()
    record_audit(
        db,
        action="commerce.support_contact_updated",
        company_id=scoped,
        user_id=user_id,
        entity_type="support_contact",
        entity_id=contact.id,
    )
    return contact


def dashboard_summary(
    db: Session,
    company_id: str | None,
    *,
    vendor_id: str | None = None,
    workspace: str = "combined",
) -> dict[str, object]:
    scoped = _company(company_id)
    if workspace not in {"shop", "online", "combined"}:
        raise ServiceError(422, "Workspace must be shop, online, or combined.")
    query = select(Order).where(Order.company_id == scoped)
    if workspace != "combined":
        channel = "pos" if workspace == "shop" else "woocommerce"
        query = query.where(Order.sales_channel == channel)
    if vendor_id:
        query = query.join(VendorOrderItem, VendorOrderItem.order_id == Order.id).where(
            VendorOrderItem.vendor_id == vendor_id
        )
    orders = list(db.scalars(query).unique().all())
    revenue = sum(
        order.total_minor for order in orders if order.status not in {"cancelled", "refunded"}
    )
    pending = sum(
        1 for order in orders if order.status in {"pending", "confirmed", "packing", "ready"}
    )
    product_query = select(func.count(Product.id)).where(Product.company_id == scoped)
    if vendor_id:
        product_query = product_query.where(Product.vendor_id == vendor_id)
    product_count = int(db.scalar(product_query) or 0)
    low_query = select(func.count(Product.id)).where(
        Product.company_id == scoped,
        Product.manage_stock.is_(True),
        Product.stock_quantity.is_not(None),
        Product.stock_quantity <= 5,
    )
    if vendor_id:
        low_query = low_query.where(Product.vendor_id == vendor_id)
    low_stock = int(db.scalar(low_query) or 0)
    reservation_count = int(
        db.scalar(
            select(func.count(StockReservation.id)).where(
                StockReservation.company_id == scoped, StockReservation.status == "reserved"
            )
        )
        or 0
    )
    return {
        "workspace": workspace,
        "sales_minor_total": revenue,
        "order_count": len(orders),
        "pending_orders": pending,
        "low_stock_count": low_stock,
        "product_count": product_count,
        "reserved_line_count": reservation_count,
        "shop_sales_minor": sum(o.total_minor for o in orders if o.sales_channel == "pos"),
        "online_sales_minor": sum(
            o.total_minor for o in orders if o.sales_channel == "woocommerce"
        ),
        "currency": "PKR",
    }


def list_vendor_stock(
    db: Session, company_id: str | None, vendor_id: str
) -> list[dict[str, object]]:
    scoped = _company(company_id)
    products = list(
        db.scalars(
            select(Product)
            .where(Product.company_id == scoped, Product.vendor_id == vendor_id)
            .order_by(Product.name)
        ).all()
    )
    warehouses = list(
        db.scalars(
            select(Warehouse)
            .where(Warehouse.company_id == scoped, Warehouse.is_active.is_(True))
            .order_by(Warehouse.code)
        ).all()
    )
    result: list[dict[str, object]] = []
    for product in products:
        for warehouse in warehouses:
            result.append(
                {
                    "product_id": product.id,
                    "name": product.name,
                    "sku": product.sku,
                    "warehouse_id": warehouse.id,
                    "warehouse_name": warehouse.name,
                    "quantity_on_hand": current_stock(
                        db,
                        company_id=scoped,
                        warehouse_id=warehouse.id,
                        product_id=product.id,
                        variant_id=None,
                    ),
                    "stock_status": product.stock_status,
                }
            )
    return result


def reserve_stock(
    db: Session, *, company_id: str | None, user_id: str, payload: StockReservationCreate
) -> StockReservation:
    scoped = _company(company_id)
    existing = db.scalar(
        select(StockReservation).where(
            StockReservation.company_id == scoped,
            StockReservation.idempotency_key == payload.idempotency_key,
        )
    )
    if existing:
        return existing
    get_warehouse(db, scoped, payload.warehouse_id)
    get_product(db, scoped, payload.product_id)
    on_hand = current_stock(
        db,
        company_id=scoped,
        warehouse_id=payload.warehouse_id,
        product_id=payload.product_id,
        variant_id=payload.variant_id,
    )
    reserved = int(
        db.scalar(
            select(func.coalesce(func.sum(StockReservation.quantity), 0)).where(
                StockReservation.company_id == scoped,
                StockReservation.warehouse_id == payload.warehouse_id,
                StockReservation.product_id == payload.product_id,
                StockReservation.variant_id == payload.variant_id,
                StockReservation.status == "reserved",
            )
        )
        or 0
    )
    if on_hand - reserved < payload.quantity:
        raise ServiceError(409, "Insufficient available stock for reservation.")
    reservation = StockReservation(company_id=scoped, **payload.model_dump())
    db.add(reservation)
    db.flush()
    record_audit(
        db,
        action="commerce.stock_reserved",
        company_id=scoped,
        user_id=user_id,
        entity_type="stock_reservation",
        entity_id=reservation.id,
        metadata={"quantity": payload.quantity, "source_id": payload.source_id},
    )
    return reservation


def create_pos_sale(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    vendor_id: str | None,
    payload: PosSaleCreate,
) -> Order:
    scoped = _company(company_id)
    if payload.idempotency_key:
        existing_orders = db.scalars(
            select(Order).where(Order.company_id == scoped, Order.order_source == "pos")
        ).all()
        for existing in existing_orders:
            if existing.metadata_json.get("idempotency_key") == payload.idempotency_key:
                return existing
    if vendor_id:
        from erp.packages.core.shop_services import vendor_shop_warehouse

        shop_warehouse = vendor_shop_warehouse(db, scoped, vendor_id)
        if payload.warehouse_id is not None and payload.warehouse_id != shop_warehouse.id:
            raise ServiceError(403, "POS sales must use this vendor's shop warehouse.")
        warehouse = shop_warehouse
    else:
        if payload.warehouse_id is None:
            raise ServiceError(422, "A warehouse is required for admin POS sales.")
        warehouse = get_warehouse(db, scoped, payload.warehouse_id)
    if not warehouse.is_active:
        raise ServiceError(409, "Cannot sell from an inactive warehouse.")
        allowed = _vendor_product_ids(db, scoped, vendor_id)
        if any(item.product_id not in allowed for item in payload.items):
            raise ServiceError(403, "POS sale contains a product outside the vendor scope.")
    sale_items: list[OrderItemCreate] = []
    for item in payload.items:
        if item.unit_price_minor is None:
            product = get_product(db, scoped, item.product_id)
            item = item.model_copy(update={"unit_price_minor": product.regular_price_minor})
        sale_items.append(item)
    customer_id = payload.customer_id
    if customer_id is None:
        customer = create_customer(
            db,
            company_id=scoped,
            user_id=user_id,
            payload=CustomerCreate(
                full_name=payload.customer_name or "Walk-in Customer",
                source_channel="pos",
            ),
        )
        customer_id = customer.id
    order = create_order(
        db,
        company_id=scoped,
        user_id=user_id,
        payload=OrderCreate(
            customer_id=customer_id,
            currency=payload.currency.upper(),
            discount_minor=payload.discount_minor,
            tax_minor=payload.tax_minor,
            notes=payload.notes,
            metadata={"idempotency_key": payload.idempotency_key}
            if payload.idempotency_key
            else {},
            items=sale_items,
        ),
    )
    order.sales_channel = "pos"
    order.order_source = "pos"
    order.reservation_status = "deducted"
    previous = order.status
    order.status = "confirmed"
    db.add(
        OrderStatusHistory(
            company_id=scoped,
            order_id=order.id,
            from_status=previous,
            to_status="confirmed",
            changed_by_id=user_id,
            reason="POS sale completed.",
        )
    )
    for item in order_items(db, order.id):
        record_stock_movement(
            db,
            company_id=scoped,
            user_id=user_id,
            payload=StockMovementCreate(
                movement_type="stock_out",
                warehouse_id=warehouse.id,
                product_id=item.product_id,
                variant_id=item.variant_id,
                quantity=item.quantity,
                reference_type="pos_sale",
                reference_id=order.id,
                reason="POS sale stock deduction.",
            ),
        )
    for payment in payload.payments:
        record_payment(db, company_id=scoped, user_id=user_id, order_id=order.id, payload=payment)
    if vendor_id:
        db.add(ShopFinanceEntry(
            company_id=scoped, vendor_id=vendor_id, entry_type="pos_sale", direction="in",
            amount_minor=order.total_minor, currency=order.currency, source_type="order", source_id=order.id,
            memo="POS sale receipt.",
        ))
    record_audit(
        db,
        action="commerce.pos_sale_completed",
        company_id=scoped,
        user_id=user_id,
        entity_type="order",
        entity_id=order.id,
        metadata={"order_number": order.order_number, "total_minor": order.total_minor},
    )
    db.flush()
    return order
