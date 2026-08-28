from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from erp.packages.core.catalog_services import get_product, require_company_id
from erp.packages.core.customer_services import get_customer
from erp.packages.core.db.models import (
    Order,
    OrderItem,
    OrderStatusHistory,
    Payment,
    ProductVariant,
    new_uuid,
)
from erp.packages.core.schemas import OrderCreate, OrderStatusChange, PaymentCreate
from erp.packages.core.services import ServiceError, record_audit, utcnow

ORDER_STATUSES = {
    "pending",
    "confirmed",
    "packing",
    "ready",
    "dispatched",
    "delivered",
    "returned",
    "cancelled",
    "refunded",
}
VALID_TRANSITIONS = {
    "pending": {"confirmed", "cancelled"},
    "confirmed": {"packing", "cancelled"},
    "packing": {"ready", "cancelled"},
    "ready": {"dispatched", "cancelled"},
    "dispatched": {"delivered", "returned"},
    "delivered": {"returned", "refunded"},
    "returned": {"refunded"},
    "cancelled": set(),
    "refunded": set(),
}
PAYMENT_STATUSES = {"pending", "paid", "failed", "refunded"}


def normalize_order_status(status: str) -> str:
    normalized = status.strip().lower()
    if normalized not in ORDER_STATUSES:
        raise ServiceError(422, f"Unsupported order status: {status}.")
    return normalized


def normalize_payment_status(status: str) -> str:
    normalized = status.strip().lower()
    if normalized not in PAYMENT_STATUSES:
        raise ServiceError(422, f"Unsupported payment status: {status}.")
    return normalized


def generate_order_number() -> str:
    return f"ORD-{utcnow():%Y%m%d}-{new_uuid()[:8].upper()}"


def order_items(db: Session, order_id: str) -> list[OrderItem]:
    return list(
        db.scalars(
            select(OrderItem).where(OrderItem.order_id == order_id).order_by(OrderItem.id)
        ).all()
    )


def order_payments(db: Session, order_id: str) -> list[Payment]:
    return list(
        db.scalars(
            select(Payment).where(Payment.order_id == order_id).order_by(Payment.created_at)
        ).all()
    )


def order_status_history(db: Session, order_id: str) -> list[OrderStatusHistory]:
    return list(
        db.scalars(
            select(OrderStatusHistory)
            .where(OrderStatusHistory.order_id == order_id)
            .order_by(OrderStatusHistory.created_at)
        ).all()
    )


def get_variant(
    db: Session,
    *,
    company_id: str,
    product_id: str,
    variant_id: str | None,
) -> ProductVariant | None:
    if not variant_id:
        return None
    variant = db.scalar(
        select(ProductVariant).where(
            ProductVariant.company_id == company_id,
            ProductVariant.product_id == product_id,
            ProductVariant.id == variant_id,
        )
    )
    if variant is None:
        raise ServiceError(404, "Product variant not found.")
    if not variant.is_active:
        raise ServiceError(409, "Cannot order an inactive product variant.")
    return variant


def list_orders(
    db: Session,
    company_id: str | None,
    *,
    status: str | None = None,
) -> list[Order]:
    scoped_company_id = require_company_id(company_id)
    query = select(Order).where(Order.company_id == scoped_company_id)
    if status:
        query = query.where(Order.status == normalize_order_status(status))
    return list(db.scalars(query.order_by(Order.created_at.desc())).all())


def get_order(db: Session, company_id: str | None, order_id: str) -> Order:
    scoped_company_id = require_company_id(company_id)
    order = db.scalar(
        select(Order).where(Order.company_id == scoped_company_id, Order.id == order_id)
    )
    if order is None:
        raise ServiceError(404, "Order not found.")
    return order


def payment_status_for(order: Order) -> str:
    if order.paid_minor <= 0:
        return "unpaid"
    if order.paid_minor < order.total_minor:
        return "partial"
    return "paid"


def create_order(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    payload: OrderCreate,
) -> Order:
    scoped_company_id = require_company_id(company_id)
    customer = get_customer(db, scoped_company_id, payload.customer_id)
    if customer.status == "archived":
        raise ServiceError(409, "Cannot create an order for an archived customer.")

    order_number = generate_order_number()
    subtotal_minor = 0
    order = Order(
        company_id=scoped_company_id,
        customer_id=customer.id,
        order_number=order_number,
        status="pending",
        currency=payload.currency.upper(),
        discount_minor=payload.discount_minor,
        tax_minor=payload.tax_minor,
        shipping_minor=payload.shipping_minor,
        notes=payload.notes,
        metadata_json=payload.metadata,
    )
    db.add(order)
    db.flush()

    for item_payload in payload.items:
        product = get_product(db, scoped_company_id, item_payload.product_id)
        if product.status == "archived":
            raise ServiceError(409, "Cannot order an archived product.")
        variant = get_variant(
            db,
            company_id=scoped_company_id,
            product_id=product.id,
            variant_id=item_payload.variant_id,
        )
        unit_price = item_payload.unit_price_minor
        if unit_price is None:
            unit_price = variant.price_minor if variant is not None else 0
        line_total = item_payload.quantity * unit_price
        subtotal_minor += line_total
        item_name = item_payload.name or product.name
        if variant is not None and variant.name:
            item_name = f"{item_name} - {variant.name}"
        db.add(
            OrderItem(
                company_id=scoped_company_id,
                order_id=order.id,
                product_id=product.id,
                variant_id=item_payload.variant_id,
                vendor_id=product.vendor_id,
                sku=item_payload.sku or (variant.sku if variant is not None else product.sku),
                name=item_name,
                quantity=item_payload.quantity,
                unit_price_minor=unit_price,
                line_total_minor=line_total,
                metadata_json=item_payload.metadata,
            )
        )

    if payload.discount_minor > subtotal_minor:
        raise ServiceError(422, "Order discount cannot exceed subtotal.")
    order.subtotal_minor = subtotal_minor
    order.total_minor = (
        subtotal_minor
        - payload.discount_minor
        + payload.tax_minor
        + payload.shipping_minor
    )
    order.payment_status = payment_status_for(order)
    db.add(
        OrderStatusHistory(
            company_id=scoped_company_id,
            order_id=order.id,
            from_status=None,
            to_status="pending",
            changed_by_id=user_id,
            reason="Order created.",
        )
    )
    db.flush()
    db.refresh(order)
    from erp.packages.core.marketplace_services import record_vendor_order_items_for_order

    record_vendor_order_items_for_order(
        db,
        company_id=scoped_company_id,
        order=order,
    )
    from erp.packages.core.push_services import enqueue_order_created

    enqueue_order_created(db, company_id=scoped_company_id, order=order)
    record_audit(
        db,
        action="orders.order_created",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="order",
        entity_id=order.id,
        metadata={"order_number": order.order_number, "total_minor": order.total_minor},
    )
    return order


def change_order_status(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    order_id: str,
    payload: OrderStatusChange,
) -> Order:
    scoped_company_id = require_company_id(company_id)
    order = get_order(db, scoped_company_id, order_id)
    target = normalize_order_status(payload.status)
    if target == order.status:
        raise ServiceError(409, "Order is already in the requested status.")
    if target not in VALID_TRANSITIONS[order.status]:
        raise ServiceError(409, f"Cannot transition order from {order.status} to {target}.")
    previous = order.status
    order.status = target
    history = OrderStatusHistory(
        company_id=scoped_company_id,
        order_id=order.id,
        from_status=previous,
        to_status=target,
        changed_by_id=user_id,
        reason=payload.reason,
    )
    db.add(history)
    db.flush()
    db.refresh(order)
    from erp.packages.core.push_services import enqueue_order_status_changed

    enqueue_order_status_changed(
        db,
        company_id=scoped_company_id,
        order=order,
        history_id=history.id,
        previous_status=previous,
    )
    record_audit(
        db,
        action="orders.status_changed",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="order",
        entity_id=order.id,
        metadata={"from_status": previous, "to_status": target},
    )
    return order


def record_payment(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    order_id: str,
    payload: PaymentCreate,
) -> Payment:
    scoped_company_id = require_company_id(company_id)
    order = get_order(db, scoped_company_id, order_id)
    if order.status in {"cancelled", "refunded"}:
        raise ServiceError(409, "Cannot record payment for a cancelled or refunded order.")
    payment_status = normalize_payment_status(payload.status)
    if payload.currency.upper() != order.currency:
        raise ServiceError(422, "Payment currency must match order currency.")
    if payment_status == "paid" and order.paid_minor + payload.amount_minor > order.total_minor:
        raise ServiceError(409, "Payment would exceed order total.")

    payment_fields = {
        "company_id": scoped_company_id,
        "order_id": order.id,
        "amount_minor": payload.amount_minor,
        "currency": payload.currency.upper(),
        "method": payload.method,
        "status": payment_status,
        "reference": payload.reference,
        "metadata_json": payload.metadata,
    }
    if payload.paid_at is not None:
        payment_fields["paid_at"] = payload.paid_at
    payment = Payment(**payment_fields)
    db.add(payment)
    if payment_status == "paid":
        order.paid_minor += payload.amount_minor
        order.payment_status = payment_status_for(order)
    db.flush()
    db.refresh(order)
    db.refresh(payment)
    if payment.status == "paid":
        from erp.packages.core.accounting_services import post_order_payment_entry

        post_order_payment_entry(
            db,
            company_id=scoped_company_id,
            user_id=user_id,
            order=order,
            payment=payment,
        )
    from erp.packages.core.push_services import enqueue_payment_recorded

    enqueue_payment_recorded(
        db,
        company_id=scoped_company_id,
        order=order,
        payment_id=payment.id,
    )
    record_audit(
        db,
        action="orders.payment_recorded",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="payment",
        entity_id=payment.id,
        metadata={"order_id": order.id, "amount_minor": payment.amount_minor},
    )
    return payment
