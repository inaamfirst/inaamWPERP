from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from erp.packages.core.catalog_services import get_product, require_company_id
from erp.packages.core.db.models import (
    Customer,
    Order,
    OrderItem,
    Payment,
    Product,
    ProductChannelListing,
    ShopFinanceEntry,
    ShopPurchase,
    ShopPurchaseLine,
    ShopSupplier,
    VendorOrderItem,
    VendorProduct,
    Warehouse,
)
from erp.packages.core.inventory_services import current_stock, record_stock_movement
from erp.packages.core.schemas import (
    ShopPurchaseCreate,
    ShopPurchasePaymentCreate,
    ShopSupplierCreate,
    StockMovementCreate,
)
from erp.packages.core.services import ServiceError, record_audit


def vendor_shop_warehouse(db: Session, company_id: str | None, vendor_id: str) -> Warehouse:
    scoped = require_company_id(company_id)
    warehouse = db.scalar(
        select(Warehouse).where(
            Warehouse.company_id == scoped,
            Warehouse.vendor_id == vendor_id,
            Warehouse.warehouse_type == "vendor_shop",
        )
    )
    if warehouse is None:
        code = f"SHOP-{vendor_id.replace('-', '')[:20]}".upper()
        warehouse = Warehouse(
            company_id=scoped,
            vendor_id=vendor_id,
            warehouse_type="vendor_shop",
            code=code,
            name="Vendor Shop",
            is_active=True,
        )
        db.add(warehouse)
        db.flush()
    return warehouse


def vendor_owns_product(db: Session, company_id: str, vendor_id: str, product: Product) -> bool:
    """Return true for both current direct ownership and legacy assignments."""
    if product.company_id != company_id:
        return False
    if product.vendor_id == vendor_id:
        return True
    return bool(
        db.scalar(
            select(VendorProduct.id).where(
                VendorProduct.company_id == company_id,
                VendorProduct.vendor_id == vendor_id,
                VendorProduct.product_id == product.id,
            )
        )
    )


def vendor_product_ids(db: Session, company_id: str, vendor_id: str) -> set[str]:
    """Return both direct and legacy product assignments for a vendor."""
    direct = db.scalars(
        select(Product.id).where(Product.company_id == company_id, Product.vendor_id == vendor_id)
    ).all()
    assigned = db.scalars(
        select(VendorProduct.product_id).where(
            VendorProduct.company_id == company_id,
            VendorProduct.vendor_id == vendor_id,
        )
    ).all()
    return set(direct) | set(assigned)


def vendor_orders_query(
    db: Session,
    *,
    company_id: str,
    vendor_id: str,
    sales_channel: str | None = None,
):
    """Find vendor orders even when a legacy order has no VendorOrderItem row."""
    product_ids = vendor_product_ids(db, company_id, vendor_id)
    conditions = [
        Order.id.in_(
            select(VendorOrderItem.order_id).where(
                VendorOrderItem.company_id == company_id,
                VendorOrderItem.vendor_id == vendor_id,
            )
        ),
        Order.id.in_(
            select(OrderItem.order_id).where(
                OrderItem.company_id == company_id,
                OrderItem.vendor_id == vendor_id,
            )
        ),
    ]
    if product_ids:
        conditions.append(
            Order.id.in_(
                select(OrderItem.order_id).where(
                    OrderItem.company_id == company_id,
                    OrderItem.product_id.in_(product_ids),
                )
            )
        )
    query = select(Order).where(Order.company_id == company_id, or_(*conditions))
    if sales_channel is not None:
        query = query.where(Order.sales_channel == sales_channel)
    return query


def list_vendor_orders(
    db: Session,
    company_id: str | None,
    vendor_id: str,
    *,
    sales_channel: str | None = None,
    limit: int | None = None,
) -> list[Order]:
    scoped = require_company_id(company_id)
    query = vendor_orders_query(
        db,
        company_id=scoped,
        vendor_id=vendor_id,
        sales_channel=sales_channel,
    ).order_by(Order.created_at.desc())
    if limit is not None:
        query = query.limit(limit)
    return list(db.scalars(query).all())


def vendor_has_order(
    db: Session,
    *,
    company_id: str | None,
    vendor_id: str,
    order_id: str,
    sales_channel: str | None = None,
) -> Order | None:
    scoped = require_company_id(company_id)
    return db.scalar(
        vendor_orders_query(
            db,
            company_id=scoped,
            vendor_id=vendor_id,
            sales_channel=sales_channel,
        ).where(Order.id == order_id)
    )


def _vendor_order_items(
    db: Session, *, company_id: str, vendor_id: str, order: Order
) -> list[OrderItem]:
    """Prefer immutable marketplace assignments; fall back for old POS records."""
    items = list(
        db.scalars(
            select(OrderItem).where(
                OrderItem.company_id == company_id,
                OrderItem.order_id == order.id,
            )
        ).all()
    )
    vendor_item_ids = set(
        db.scalars(
            select(VendorOrderItem.order_item_id).where(
                VendorOrderItem.company_id == company_id,
                VendorOrderItem.vendor_id == vendor_id,
                VendorOrderItem.order_id == order.id,
            )
        ).all()
    )
    if vendor_item_ids:
        return [item for item in items if item.id in vendor_item_ids]
    product_ids = vendor_product_ids(db, company_id, vendor_id)
    return [
        item
        for item in items
        if item.vendor_id == vendor_id or item.product_id in product_ids
    ]


def queue_published_shop_stock_sync(
    db: Session,
    *,
    company_id: str | None,
    vendor_id: str,
    product_id: str,
) -> None:
    """Push local stock changes only for products explicitly published online."""
    scoped = require_company_id(company_id)
    product = get_product(db, scoped, product_id)
    if not vendor_owns_product(db, scoped, vendor_id, product):
        raise ServiceError(403, "Product is outside the vendor shop.")
    listing = db.scalar(
        select(ProductChannelListing).where(
            ProductChannelListing.company_id == scoped,
            ProductChannelListing.product_id == product.id,
            ProductChannelListing.channel == "woocommerce",
            ProductChannelListing.listing_status == "published",
        )
    )
    if listing is None:
        return
    from erp.packages.core.woocommerce_services import enqueue_product_sync

    try:
        enqueue_product_sync(db, company_id=scoped, product=product)
    except ServiceError as exc:
        if exc.status_code != 404 or exc.message != "WooCommerce is not configured.":
            raise


def sync_product_catalog_quantity_from_shop(
    db: Session,
    *,
    company_id: str | None,
    vendor_id: str,
    product_id: str,
) -> int:
    """Copy the authoritative shop ledger balance onto the catalog product."""
    scoped = require_company_id(company_id)
    product = get_product(db, scoped, product_id)
    if not vendor_owns_product(db, scoped, vendor_id, product):
        raise ServiceError(403, "Product is outside the vendor shop.")
    warehouse = vendor_shop_warehouse(db, scoped, vendor_id)
    quantity = current_stock(
        db,
        company_id=scoped,
        warehouse_id=warehouse.id,
        product_id=product.id,
        variant_id=None,
    )
    product.stock_quantity = quantity
    product.manage_stock = True
    product.stock_status = "outofstock" if quantity <= 0 else "instock"
    db.flush()
    return quantity


def sync_product_shop_stock_quantity(
    db: Session,
    *,
    company_id: str | None,
    vendor_id: str,
    user_id: str,
    product_id: str,
    target_quantity: int | None,
    reason: str,
    reference_type: str,
    reference_id: str,
) -> int:
    """Reconcile an editor's numeric quantity against the shop stock ledger."""
    if target_quantity is None:
        return sync_product_catalog_quantity_from_shop(
            db,
            company_id=company_id,
            vendor_id=vendor_id,
            product_id=product_id,
        )
    if target_quantity < 0:
        raise ServiceError(422, "Shop stock quantity cannot be negative.")
    scoped = require_company_id(company_id)
    product = get_product(db, scoped, product_id)
    if not vendor_owns_product(db, scoped, vendor_id, product):
        raise ServiceError(403, "Product is outside the vendor shop.")
    warehouse = vendor_shop_warehouse(db, scoped, vendor_id)
    current = current_stock(
        db,
        company_id=scoped,
        warehouse_id=warehouse.id,
        product_id=product.id,
        variant_id=None,
    )
    delta = target_quantity - current
    if delta:
        record_stock_movement(
            db,
            company_id=scoped,
            user_id=user_id,
            payload=StockMovementCreate(
                movement_type="adjustment",
                warehouse_id=warehouse.id,
                product_id=product.id,
                quantity_delta=delta,
                reference_type=reference_type,
                reference_id=reference_id,
                reason=reason,
            ),
        )
    quantity = sync_product_catalog_quantity_from_shop(
        db,
        company_id=scoped,
        vendor_id=vendor_id,
        product_id=product.id,
    )
    if delta:
        queue_published_shop_stock_sync(
            db,
            company_id=scoped,
            vendor_id=vendor_id,
            product_id=product.id,
        )
    return quantity


def _supplier(db: Session, company_id: str, vendor_id: str, supplier_id: str) -> ShopSupplier:
    supplier = db.scalar(
        select(ShopSupplier).where(
            ShopSupplier.company_id == company_id,
            ShopSupplier.vendor_id == vendor_id,
            ShopSupplier.id == supplier_id,
        )
    )
    if supplier is None:
        raise ServiceError(404, "Shop supplier not found.")
    return supplier


def list_suppliers(db: Session, company_id: str | None, vendor_id: str) -> list[ShopSupplier]:
    scoped = require_company_id(company_id)
    return list(
        db.scalars(
            select(ShopSupplier)
            .where(ShopSupplier.company_id == scoped, ShopSupplier.vendor_id == vendor_id)
            .order_by(ShopSupplier.name)
        ).all()
    )


def supplier_outstanding(db: Session, company_id: str | None, vendor_id: str, supplier_id: str) -> int:
    scoped = require_company_id(company_id)
    return int(db.scalar(select(func.coalesce(func.sum(ShopPurchase.total_minor - ShopPurchase.paid_minor), 0)).where(
        ShopPurchase.company_id == scoped,
        ShopPurchase.vendor_id == vendor_id,
        ShopPurchase.supplier_id == supplier_id,
    )) or 0)


def update_supplier(
    db: Session, *, company_id: str | None, vendor_id: str, user_id: str,
    supplier_id: str, payload: ShopSupplierCreate,
) -> ShopSupplier:
    scoped = require_company_id(company_id)
    supplier = _supplier(db, scoped, vendor_id, supplier_id)
    for key, value in payload.model_dump().items():
        setattr(supplier, key, value)
    record_audit(
        db, action="shop.supplier_updated", company_id=scoped, user_id=user_id,
        entity_type="shop_supplier", entity_id=supplier.id, metadata={"vendor_id": vendor_id},
    )
    db.flush()
    return supplier


def list_shop_catalog(db: Session, company_id: str | None, vendor_id: str) -> list[dict[str, object]]:
    """Return the small, POS-friendly catalog for one vendor's shop."""
    scoped = require_company_id(company_id)
    warehouse = vendor_shop_warehouse(db, scoped, vendor_id)
    direct_ids = db.scalars(
        select(Product.id).where(Product.company_id == scoped, Product.vendor_id == vendor_id)
    ).all()
    assigned_ids = db.scalars(
        select(VendorProduct.product_id).where(
            VendorProduct.company_id == scoped,
            VendorProduct.vendor_id == vendor_id,
        )
    ).all()
    products = db.scalars(
        select(Product).where(
            Product.company_id == scoped,
            Product.id.in_(set(direct_ids) | set(assigned_ids)),
            Product.status != "archived",
        ).order_by(Product.name)
    ).all()
    listings = {
        row.product_id: row
        for row in db.scalars(
            select(ProductChannelListing).where(
                ProductChannelListing.company_id == scoped,
                ProductChannelListing.channel == "woocommerce",
            )
        ).all()
    }
    result: list[dict[str, object]] = []
    for product in products:
        quantity = current_stock(
            db, company_id=scoped, warehouse_id=warehouse.id,
            product_id=product.id, variant_id=None,
        )
        listing = listings.get(product.id)
        result.append({
            "id": product.id,
            "name": product.name,
            "sku": product.sku,
            "barcode": product.barcode,
            "regular_price_minor": product.regular_price_minor,
            "sale_price_minor": product.sale_price_minor,
            "stock_quantity": quantity,
            "stock_status": product.stock_status,
            "low_stock": quantity <= 5,
            "online_status": listing.listing_status if listing else "private",
            "category_id": product.category_id,
        })
    return result


def list_purchases(db: Session, company_id: str | None, vendor_id: str, limit: int = 100) -> list[ShopPurchase]:
    scoped = require_company_id(company_id)
    return list(db.scalars(
        select(ShopPurchase).where(
            ShopPurchase.company_id == scoped, ShopPurchase.vendor_id == vendor_id,
        ).order_by(ShopPurchase.created_at.desc()).limit(limit)
    ).all())


def purchase_detail(db: Session, company_id: str | None, vendor_id: str, purchase_id: str) -> dict[str, object]:
    scoped = require_company_id(company_id)
    purchase = db.scalar(select(ShopPurchase).where(
        ShopPurchase.company_id == scoped, ShopPurchase.vendor_id == vendor_id,
        ShopPurchase.id == purchase_id,
    ))
    if purchase is None:
        raise ServiceError(404, "Shop purchase not found.")
    lines = db.scalars(select(ShopPurchaseLine).where(ShopPurchaseLine.purchase_id == purchase.id)).all()
    return {"purchase": purchase, "lines": list(lines)}


def list_recent_sales(
    db: Session,
    company_id: str | None,
    vendor_id: str,
    limit: int = 50,
    sales_channel: str | None = "pos",
) -> list[dict[str, object]]:
    scoped = require_company_id(company_id)
    orders = list_vendor_orders(
        db,
        scoped,
        vendor_id,
        sales_channel=sales_channel,
        limit=limit,
    )
    result: list[dict[str, object]] = []
    for order in orders:
        customer = db.get(Customer, order.customer_id)
        items = _vendor_order_items(
            db, company_id=scoped, vendor_id=vendor_id, order=order
        )
        payments = list(
            db.scalars(
                select(Payment)
                .where(Payment.company_id == scoped, Payment.order_id == order.id)
                .order_by(Payment.created_at)
            ).all()
        )
        payment = payments[0] if payments else None
        line_total = sum(item.line_total_minor for item in items)
        result.append({
            "id": order.id,
            "bill_number": order.order_number,
            "created_at": order.created_at,
            "customer": customer.full_name if customer else "Walk-in Customer",
            # A POS order is one vendor's sale. For a multi-vendor online order,
            # report only the authenticated vendor's lines.
            "total_minor": order.total_minor if order.sales_channel == "pos" else line_total,
            "order_total_minor": order.total_minor,
            "item_quantity": sum(item.quantity for item in items),
            "items": [
                {
                    "id": item.id,
                    "name": item.name,
                    "sku": item.sku,
                    "quantity": item.quantity,
                    "line_total_minor": item.line_total_minor,
                }
                for item in items
            ],
            "currency": order.currency,
            "channel": order.sales_channel,
            "payment_method": payment.method if payment else "unpaid",
            "payment_status": order.payment_status,
            "status": order.status,
            "reservation_status": order.reservation_status,
            "paid_minor": order.paid_minor,
            "payments": [
                {
                    "method": row.method,
                    "status": row.status,
                    "amount_minor": row.amount_minor,
                }
                for row in payments
            ],
        })
    return result


def create_supplier(
    db: Session, *, company_id: str | None, vendor_id: str, user_id: str, payload: ShopSupplierCreate
) -> ShopSupplier:
    scoped = require_company_id(company_id)
    supplier = ShopSupplier(company_id=scoped, vendor_id=vendor_id, **payload.model_dump())
    db.add(supplier)
    db.flush()
    record_audit(
        db, action="shop.supplier_created", company_id=scoped, user_id=user_id,
        entity_type="shop_supplier", entity_id=supplier.id, metadata={"vendor_id": vendor_id},
    )
    return supplier


def _purchase_number(db: Session, company_id: str, vendor_id: str) -> str:
    count = int(db.scalar(select(func.count(ShopPurchase.id)).where(
        ShopPurchase.company_id == company_id, ShopPurchase.vendor_id == vendor_id
    )) or 0)
    return f"PUR-{count + 1:06d}"


def create_purchase(
    db: Session, *, company_id: str | None, vendor_id: str, user_id: str, payload: ShopPurchaseCreate
) -> ShopPurchase:
    scoped = require_company_id(company_id)
    _supplier(db, scoped, vendor_id, payload.supplier_id)
    warehouse = vendor_shop_warehouse(db, scoped, vendor_id)
    total = sum(line.quantity * line.unit_cost_minor for line in payload.items)
    if payload.payment_minor > total:
        raise ServiceError(422, "Payment cannot exceed the purchase total.")
    purchase = ShopPurchase(
        company_id=scoped, vendor_id=vendor_id, supplier_id=payload.supplier_id,
        warehouse_id=warehouse.id, purchase_number=_purchase_number(db, scoped, vendor_id),
        currency=payload.currency.upper(), total_minor=total, paid_minor=payload.payment_minor,
        payment_status="paid" if payload.payment_minor == total else "partial" if payload.payment_minor else "unpaid",
        notes=payload.notes,
    )
    db.add(purchase)
    db.flush()
    for line in payload.items:
        product = get_product(db, scoped, line.product_id)
        if not vendor_owns_product(db, scoped, vendor_id, product):
            raise ServiceError(403, "Purchase contains a product outside the vendor shop.")
        db.add(ShopPurchaseLine(
            purchase_id=purchase.id, product_id=product.id, variant_id=line.variant_id,
            quantity=line.quantity, unit_cost_minor=line.unit_cost_minor,
            line_total_minor=line.quantity * line.unit_cost_minor,
        ))
        record_stock_movement(
            db, company_id=scoped, user_id=user_id,
            payload=StockMovementCreate(
                movement_type="stock_in", warehouse_id=warehouse.id, product_id=product.id,
                variant_id=line.variant_id, quantity=line.quantity, reference_type="shop_purchase",
                reference_id=purchase.id, reason="Vendor shop purchase receipt.",
            ),
        )
        if line.variant_id is None:
            sync_product_catalog_quantity_from_shop(
                db,
                company_id=scoped,
                vendor_id=vendor_id,
                product_id=product.id,
            )
            queue_published_shop_stock_sync(
                db,
                company_id=scoped,
                vendor_id=vendor_id,
                product_id=product.id,
            )
    if payload.payment_minor:
        db.add(ShopFinanceEntry(
            company_id=scoped, vendor_id=vendor_id, entry_type="purchase_payment", direction="out",
            amount_minor=payload.payment_minor, currency=purchase.currency, source_type="shop_purchase",
            source_id=purchase.id, memo=payload.notes,
        ))
    record_audit(
        db, action="shop.purchase_received", company_id=scoped, user_id=user_id,
        entity_type="shop_purchase", entity_id=purchase.id,
        metadata={"vendor_id": vendor_id, "total_minor": total},
    )
    db.flush()
    return purchase


def pay_purchase(
    db: Session, *, company_id: str | None, vendor_id: str, user_id: str, purchase_id: str,
    payload: ShopPurchasePaymentCreate,
) -> ShopPurchase:
    scoped = require_company_id(company_id)
    purchase = db.scalar(select(ShopPurchase).where(
        ShopPurchase.company_id == scoped, ShopPurchase.vendor_id == vendor_id, ShopPurchase.id == purchase_id
    ))
    if purchase is None:
        raise ServiceError(404, "Shop purchase not found.")
    if purchase.paid_minor + payload.amount_minor > purchase.total_minor:
        raise ServiceError(422, "Payment cannot exceed the outstanding purchase balance.")
    purchase.paid_minor += payload.amount_minor
    purchase.payment_status = "paid" if purchase.paid_minor == purchase.total_minor else "partial"
    db.add(ShopFinanceEntry(
        company_id=scoped, vendor_id=vendor_id, entry_type="purchase_payment", direction="out",
        amount_minor=payload.amount_minor, currency=purchase.currency, source_type="shop_purchase",
        source_id=purchase.id, memo=payload.memo,
    ))
    record_audit(
        db, action="shop.purchase_paid", company_id=scoped, user_id=user_id,
        entity_type="shop_purchase", entity_id=purchase.id, metadata={"amount_minor": payload.amount_minor},
    )
    db.flush()
    return purchase


def overview(db: Session, company_id: str | None, vendor_id: str) -> dict[str, object]:
    scoped = require_company_id(company_id)
    purchases = list(db.scalars(select(ShopPurchase).where(
        ShopPurchase.company_id == scoped, ShopPurchase.vendor_id == vendor_id
    )).all())
    finance = list(db.scalars(select(ShopFinanceEntry).where(
        ShopFinanceEntry.company_id == scoped, ShopFinanceEntry.vendor_id == vendor_id
    )).all())
    shop_sales = list_recent_sales(
        db, scoped, vendor_id, limit=10_000, sales_channel="pos"
    )
    online_sales = list_recent_sales(
        db, scoped, vendor_id, limit=10_000, sales_channel="woocommerce"
    )

    def channel_summary(rows: list[dict[str, object]]) -> dict[str, object]:
        active = [row for row in rows if row["status"] not in {"cancelled", "refunded"}]
        payment_methods: dict[str, int] = {}
        for row in active:
            for payment in row["payments"]:
                if payment["status"] != "paid":
                    continue
                method = str(payment["method"] or "other")
                payment_methods[method] = payment_methods.get(method, 0) + int(
                    payment["amount_minor"]
                )
        return {
            "sales_count": len(active),
            "units_sold": sum(int(row["item_quantity"]) for row in active),
            "sales_minor": sum(int(row["total_minor"]) for row in active),
            "paid_minor": sum(
                min(int(row["paid_minor"]), int(row["total_minor"])) for row in active
            ),
            "payment_methods": payment_methods,
        }

    online_payable_minor = int(
        db.scalar(
            select(func.coalesce(func.sum(VendorOrderItem.payable_minor), 0)).join(
                Order,
                (Order.id == VendorOrderItem.order_id)
                & (Order.company_id == VendorOrderItem.company_id),
            ).where(
                VendorOrderItem.company_id == scoped,
                VendorOrderItem.vendor_id == vendor_id,
                Order.sales_channel == "woocommerce",
                Order.status.not_in({"cancelled", "refunded"}),
            )
        )
        or 0
    )
    shop_summary = channel_summary(shop_sales)
    online_summary = channel_summary(online_sales)
    online_summary["vendor_payable_minor"] = online_payable_minor
    shared_inventory = {
        "purchase_total_minor": sum(row.total_minor for row in purchases),
        "supplier_payable_minor": sum(row.total_minor - row.paid_minor for row in purchases),
        "cash_out_minor": sum(row.amount_minor for row in finance if row.direction == "out"),
    }
    return {
        # Keep legacy fields during the frontend rollout.
        "purchase_total_minor": shared_inventory["purchase_total_minor"],
        "supplier_payable_minor": shared_inventory["supplier_payable_minor"],
        "cash_in_minor": sum(row.amount_minor for row in finance if row.direction == "in"),
        "cash_out_minor": shared_inventory["cash_out_minor"],
        "shop": shop_summary,
        "online": online_summary,
        "shared_inventory": shared_inventory,
        "currency": "PKR",
    }
