from __future__ import annotations

from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from erp.packages.core.catalog_services import require_company_id
from erp.packages.core.db.models import (
    Customer,
    CustomerAddress,
    DeliveryAssignment,
    DeliveryStatusHistory,
    Order,
    Role,
    User,
    UserRole,
)
from erp.packages.core.services import ServiceError, record_audit, utcnow

DELIVERY_STATUSES = {
    "assigned",
    "picked_up",
    "out_for_delivery",
    "delivered",
    "failed",
    "cancelled",
}
DELIVERY_TRANSITIONS = {
    "assigned": {"picked_up", "failed", "cancelled"},
    "picked_up": {"out_for_delivery", "failed"},
    "out_for_delivery": {"delivered", "failed"},
    "delivered": set(),
    "failed": set(),
    "cancelled": set(),
}
READY_ORDER_STATUSES = {"ready", "dispatched"}


def _company(company_id: str | None) -> str:
    return require_company_id(company_id)


def _rider(db: Session, company_id: str, user_id: str) -> User:
    rider = db.scalar(
        select(User)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(
            User.id == user_id,
            User.company_id == company_id,
            User.is_active.is_(True),
            User.account_status == "active",
            Role.company_id == company_id,
            Role.name == "Rider",
        )
    )
    if rider is None:
        raise ServiceError(422, "The selected user is not an active rider in this workspace.")
    return rider


def list_riders(db: Session, company_id: str | None) -> list[User]:
    scoped = _company(company_id)
    return list(
        db.scalars(
            select(User)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(
                User.company_id == scoped,
                User.is_active.is_(True),
                User.account_status == "active",
                Role.company_id == scoped,
                Role.name == "Rider",
            )
            .order_by(User.full_name, User.username)
        )
        .unique()
        .all()
    )


def _order_address(
    db: Session, company_id: str, order: Order, customer: Customer
) -> dict[str, Any]:
    metadata = order.metadata_json if isinstance(order.metadata_json, dict) else {}
    raw = metadata.get("shipping_address")
    if isinstance(raw, dict) and str(raw.get("line1") or "").strip():
        return {
            "recipient_name": str(raw.get("recipient_name") or customer.full_name),
            "recipient_phone": raw.get("phone") or customer.phone,
            "address_line1": str(raw["line1"]).strip(),
            "address_line2": raw.get("line2"),
            "city": raw.get("city"),
            "state": raw.get("state"),
            "postal_code": raw.get("postal_code"),
            "country": str(raw.get("country") or "PK").upper(),
        }

    address = db.scalar(
        select(CustomerAddress).where(
            CustomerAddress.company_id == company_id,
            CustomerAddress.customer_id == customer.id,
            CustomerAddress.is_default.is_(True),
        )
    )
    if address is None:
        raise ServiceError(
            422,
            "The order has no shipping address and the customer has no default address.",
        )
    return {
        "recipient_name": address.recipient_name or customer.full_name,
        "recipient_phone": address.phone or customer.phone,
        "address_line1": address.line1,
        "address_line2": address.line2,
        "city": address.city,
        "state": address.state,
        "postal_code": address.postal_code,
        "country": address.country,
    }


def _history(db: Session, company_id: str, assignment_id: str) -> list[DeliveryStatusHistory]:
    return list(
        db.scalars(
            select(DeliveryStatusHistory)
            .where(
                DeliveryStatusHistory.company_id == company_id,
                DeliveryStatusHistory.delivery_assignment_id == assignment_id,
            )
            .order_by(DeliveryStatusHistory.created_at, DeliveryStatusHistory.id)
        ).all()
    )


def assignment_out(db: Session, assignment: DeliveryAssignment) -> dict[str, Any]:
    order = db.get(Order, assignment.order_id)
    customer = db.get(Customer, order.customer_id) if order else None
    rider = db.get(User, assignment.rider_user_id)
    if order is None or customer is None:
        raise ServiceError(500, "Delivery assignment references missing order data.")
    return {
        "id": assignment.id,
        "company_id": assignment.company_id,
        "order_id": order.id,
        "order_number": order.order_number,
        "order_status": order.status,
        "order_total_minor": order.total_minor,
        "payment_status": order.payment_status,
        "rider_user_id": assignment.rider_user_id,
        "rider_username": rider.username if rider else None,
        "rider_name": rider.full_name if rider else None,
        "status": assignment.status,
        "recipient_name": assignment.recipient_name,
        "recipient_phone": assignment.recipient_phone,
        "address_line1": assignment.address_line1,
        "address_line2": assignment.address_line2,
        "city": assignment.city,
        "state": assignment.state,
        "postal_code": assignment.postal_code,
        "country": assignment.country,
        "picked_up_at": assignment.picked_up_at,
        "out_for_delivery_at": assignment.out_for_delivery_at,
        "delivered_at": assignment.delivered_at,
        "failed_at": assignment.failed_at,
        "failure_reason": assignment.failure_reason,
        "created_at": assignment.created_at,
        "updated_at": assignment.updated_at,
        "history": [
            {
                "id": row.id,
                "delivery_assignment_id": row.delivery_assignment_id,
                "from_status": row.from_status,
                "to_status": row.to_status,
                "changed_by_id": row.changed_by_id,
                "reason": row.reason,
                "created_at": row.created_at,
            }
            for row in _history(db, assignment.company_id, assignment.id)
        ],
    }


def list_assignments(
    db: Session,
    company_id: str | None,
    *,
    rider_user_id: str | None = None,
    status: str | None = None,
) -> list[DeliveryAssignment]:
    scoped = _company(company_id)
    query = select(DeliveryAssignment).where(DeliveryAssignment.company_id == scoped)
    if rider_user_id:
        query = query.where(DeliveryAssignment.rider_user_id == rider_user_id)
    if status:
        if status not in DELIVERY_STATUSES:
            raise ServiceError(422, f"Unsupported delivery status: {status}.")
        query = query.where(DeliveryAssignment.status == status)
    return list(db.scalars(query.order_by(DeliveryAssignment.created_at.desc())).all())


def unassigned_orders(db: Session, company_id: str | None) -> list[Order]:
    scoped = _company(company_id)
    return list(
        db.scalars(
            select(Order)
            .outerjoin(
                DeliveryAssignment,
                and_(
                    DeliveryAssignment.order_id == Order.id,
                    DeliveryAssignment.company_id == scoped,
                ),
            )
            .where(
                Order.company_id == scoped,
                Order.status.in_(READY_ORDER_STATUSES),
                DeliveryAssignment.id.is_(None),
            )
            .order_by(Order.created_at.desc())
        ).all()
    )


def create_assignment(
    db: Session,
    *,
    company_id: str | None,
    admin_user_id: str,
    order_id: str,
    rider_user_id: str,
) -> DeliveryAssignment:
    scoped = _company(company_id)
    order = db.scalar(select(Order).where(Order.company_id == scoped, Order.id == order_id))
    if order is None:
        raise ServiceError(404, "Order not found.")
    if order.status not in READY_ORDER_STATUSES:
        raise ServiceError(409, "Only ready or dispatched orders can be assigned for delivery.")
    existing = db.scalar(
        select(DeliveryAssignment).where(
            DeliveryAssignment.company_id == scoped,
            DeliveryAssignment.order_id == order.id,
        )
    )
    if existing is not None:
        raise ServiceError(409, "This order already has a delivery assignment.")

    rider = _rider(db, scoped, rider_user_id)
    customer = db.get(Customer, order.customer_id)
    if customer is None or customer.company_id != scoped:
        raise ServiceError(500, "Order customer data is unavailable.")
    address = _order_address(db, scoped, order, customer)
    assignment = DeliveryAssignment(
        company_id=scoped,
        order_id=order.id,
        rider_user_id=rider.id,
        assigned_by_id=admin_user_id,
        status="assigned",
        **address,
    )
    db.add(assignment)
    db.flush()
    history = DeliveryStatusHistory(
        company_id=scoped,
        delivery_assignment_id=assignment.id,
        from_status=None,
        to_status="assigned",
        changed_by_id=admin_user_id,
        reason="Delivery assigned.",
    )
    db.add(history)
    record_audit(
        db,
        action="delivery.assignment_created",
        company_id=scoped,
        user_id=admin_user_id,
        entity_type="delivery_assignment",
        entity_id=assignment.id,
        metadata={"order_id": order.id, "rider_user_id": rider.id},
    )
    from erp.packages.core.push_services import enqueue_delivery_event

    enqueue_delivery_event(
        db,
        company_id=scoped,
        order_id=order.id,
        event_type="delivery_assignment_created",
        event_key=f"delivery-assignment:{assignment.id}",
        title="Delivery assigned",
        body=f"Order {order.order_number} has been assigned for delivery.",
    )
    db.flush()
    return assignment


def reassign_assignment(
    db: Session,
    *,
    company_id: str | None,
    admin_user_id: str,
    assignment_id: str,
    rider_user_id: str,
) -> DeliveryAssignment:
    scoped = _company(company_id)
    assignment = db.scalar(
        select(DeliveryAssignment).where(
            DeliveryAssignment.company_id == scoped,
            DeliveryAssignment.id == assignment_id,
        )
    )
    if assignment is None:
        raise ServiceError(404, "Delivery assignment not found.")
    if assignment.status in {"delivered", "cancelled"}:
        raise ServiceError(409, "Completed or cancelled deliveries cannot be reassigned.")
    rider = _rider(db, scoped, rider_user_id)
    previous_rider_id = assignment.rider_user_id
    assignment.rider_user_id = rider.id
    assignment.assigned_by_id = admin_user_id
    record_audit(
        db,
        action="delivery.assignment_reassigned",
        company_id=scoped,
        user_id=admin_user_id,
        entity_type="delivery_assignment",
        entity_id=assignment.id,
        metadata={"from_rider_user_id": previous_rider_id, "rider_user_id": rider.id},
    )
    order = db.get(Order, assignment.order_id)
    if order is not None:
        from erp.packages.core.push_services import enqueue_delivery_event

        enqueue_delivery_event(
            db,
            company_id=scoped,
            order_id=order.id,
            event_type="delivery_assignment_reassigned",
            event_key=f"delivery-reassigned:{assignment.id}:{rider.id}",
            title="Delivery reassigned",
            body=f"Delivery for order {order.order_number} was reassigned.",
        )
    db.flush()
    return assignment


def change_assignment_status(
    db: Session,
    *,
    company_id: str | None,
    rider_user_id: str,
    assignment_id: str,
    status: str,
    reason: str | None = None,
) -> DeliveryAssignment:
    scoped = _company(company_id)
    if status not in DELIVERY_STATUSES:
        raise ServiceError(422, f"Unsupported delivery status: {status}.")
    assignment = db.scalar(
        select(DeliveryAssignment).where(
            DeliveryAssignment.company_id == scoped,
            DeliveryAssignment.id == assignment_id,
            DeliveryAssignment.rider_user_id == rider_user_id,
        )
    )
    if assignment is None:
        raise ServiceError(404, "Delivery assignment not found.")
    if status not in DELIVERY_TRANSITIONS[assignment.status]:
        raise ServiceError(409, f"Cannot transition delivery from {assignment.status} to {status}.")
    if status in {"failed", "cancelled"} and not (reason or "").strip():
        raise ServiceError(422, f"A reason is required when marking a delivery {status}.")

    previous = assignment.status
    now = utcnow()
    assignment.status = status
    if status == "picked_up":
        assignment.picked_up_at = now
    elif status == "out_for_delivery":
        assignment.out_for_delivery_at = now
    elif status == "delivered":
        assignment.delivered_at = now
    elif status == "failed":
        assignment.failed_at = now
        assignment.failure_reason = reason
    elif status == "cancelled":
        assignment.failure_reason = reason
    history = DeliveryStatusHistory(
        company_id=scoped,
        delivery_assignment_id=assignment.id,
        from_status=previous,
        to_status=status,
        changed_by_id=rider_user_id,
        reason=reason,
    )
    db.add(history)
    record_audit(
        db,
        action="delivery.status_changed",
        company_id=scoped,
        user_id=rider_user_id,
        entity_type="delivery_assignment",
        entity_id=assignment.id,
        metadata={"from_status": previous, "to_status": status},
    )
    db.flush()
    order = db.get(Order, assignment.order_id)
    if order is not None:
        if status == "delivered":
            # A sale may only move to finance review after both delivery and
            # confirmed payment conditions are met. This is a no-op until the
            # payment side is complete.
            from erp.packages.core.finance_services import refresh_vendor_finance_eligibility

            refresh_vendor_finance_eligibility(db, company_id=scoped, order_id=order.id)
        from erp.packages.core.push_services import enqueue_delivery_event

        enqueue_delivery_event(
            db,
            company_id=scoped,
            order_id=order.id,
            event_type="delivery_status_changed",
            event_key=f"delivery-status:{history.id}",
            title="Delivery status updated",
            body=f"Delivery for order {order.order_number} is now {status.replace('_', ' ')}.",
        )
    db.flush()
    return assignment


def dashboard_summary(
    db: Session, company_id: str | None, *, rider_user_id: str | None = None
) -> dict[str, int]:
    scoped = _company(company_id)
    filters = [DeliveryAssignment.company_id == scoped]
    if rider_user_id:
        filters.append(DeliveryAssignment.rider_user_id == rider_user_id)

    def count(status: str) -> int:
        return int(
            db.scalar(
                select(func.count(DeliveryAssignment.id)).where(
                    *filters, DeliveryAssignment.status == status
                )
            )
            or 0
        )

    unassigned_count = len(unassigned_orders(db, scoped)) if not rider_user_id else 0
    return {
        "assigned_count": count("assigned"),
        "picked_up_count": count("picked_up"),
        "out_for_delivery_count": count("out_for_delivery"),
        "delivered_count": count("delivered"),
        "failed_count": count("failed"),
        "cancelled_count": count("cancelled"),
        "unassigned_count": unassigned_count,
        "active_rider_count": len(list_riders(db, scoped)) if not rider_user_id else 0,
    }
