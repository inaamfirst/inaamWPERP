from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from sqlalchemy import distinct, or_, select
from sqlalchemy.orm import Session

from erp.packages.core.config import get_settings
from erp.packages.core.db.models import (
    Order,
    OrderItem,
    Permission,
    PushDeliveryLog,
    PushNotification,
    PushSubscription,
    Role,
    RolePermission,
    User,
    UserRole,
    VendorUser,
    new_uuid,
)
from erp.packages.core.schemas import PushSubscriptionCreate
from erp.packages.core.services import ServiceError, utcnow

PUSH_ADAPTER = "webpush"
MAX_BODY_LENGTH = 500


def push_subscription_out(subscription: PushSubscription) -> dict[str, Any]:
    return {
        "id": subscription.id,
        "endpoint": subscription.endpoint,
        "expiration_at": subscription.expiration_at,
        "user_agent": subscription.user_agent,
        "device_label": subscription.device_label,
        "is_active": subscription.is_active,
        "last_seen_at": subscription.last_seen_at,
        "created_at": subscription.created_at,
        "updated_at": subscription.updated_at,
    }


def push_notification_out(notification: PushNotification) -> dict[str, Any]:
    return {
        "id": notification.id,
        "event_type": notification.event_type,
        "order_id": notification.order_id,
        "vendor_id": notification.vendor_id,
        "title": notification.title,
        "body": notification.body,
        "target_route": notification.target_route,
        "status": notification.status,
        "attempts": notification.attempts,
        "scheduled_at": notification.scheduled_at,
        "sent_at": notification.sent_at,
        "failed_at": notification.failed_at,
        "last_error": notification.last_error,
        "created_at": notification.created_at,
        "updated_at": notification.updated_at,
    }


def _eligible_admin_ids(
    db: Session,
    company_id: str,
    permissions: tuple[str, ...] = ("orders.view",),
) -> set[str]:
    rows = db.scalars(
        select(distinct(User.id))
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .join(RolePermission, RolePermission.role_id == Role.id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(
            User.company_id == company_id,
            User.is_active.is_(True),
            User.account_status == "active",
            Role.name != "Vendor",
            Permission.key.in_(permissions),
        )
    ).all()
    return {str(value) for value in rows}


def _eligible_vendor_ids(db: Session, company_id: str, vendor_id: str) -> set[str]:
    rows = db.scalars(
        select(distinct(User.id))
        .join(VendorUser, VendorUser.user_id == User.id)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .join(RolePermission, RolePermission.role_id == Role.id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(
            User.company_id == company_id,
            VendorUser.company_id == company_id,
            VendorUser.vendor_id == vendor_id,
            User.is_active.is_(True),
            User.account_status == "active",
            Permission.key == "vendor.orders.view",
        )
    ).all()
    return {str(value) for value in rows}


def _order_vendor_ids(db: Session, company_id: str, order_id: str) -> set[str]:
    rows = db.scalars(
        select(distinct(OrderItem.vendor_id)).where(
            OrderItem.company_id == company_id,
            OrderItem.order_id == order_id,
            OrderItem.vendor_id.is_not(None),
        )
    ).all()
    return {str(value) for value in rows if value}


def _queue_notification(
    db: Session,
    *,
    company_id: str,
    recipient_user_id: str,
    event_type: str,
    event_key: str,
    title: str,
    body: str,
    target_route: str,
    order_id: str | None = None,
    vendor_id: str | None = None,
) -> PushNotification | None:
    settings = get_settings()
    if not settings.effective_push_enabled:
        return None
    idempotency_key = f"{event_key}:user:{recipient_user_id}"
    existing = db.scalar(
        select(PushNotification).where(PushNotification.idempotency_key == idempotency_key)
    )
    if existing is not None:
        return existing
    safe_body = body[:MAX_BODY_LENGTH]
    notification = PushNotification(
        id=new_uuid(),
        company_id=company_id,
        recipient_user_id=recipient_user_id,
        event_type=event_type,
        order_id=order_id,
        vendor_id=vendor_id,
        title=title[:160],
        body=safe_body,
        target_route=target_route[:255],
        payload_json={
            "event_type": event_type,
            "order_id": order_id,
            "vendor_id": vendor_id,
            "scope": "vendor" if vendor_id else "company",
        },
        status="queued",
        idempotency_key=idempotency_key,
    )
    db.add(notification)
    return notification


def enqueue_order_event(
    db: Session,
    *,
    company_id: str,
    order_id: str,
    event_type: str,
    event_key: str,
    title: str,
    body: str,
    vendor_ids: set[str] | None = None,
    admin_permissions: tuple[str, ...] = ("orders.view",),
) -> list[PushNotification]:
    order = db.scalar(select(Order).where(Order.company_id == company_id, Order.id == order_id))
    if order is None:
        return []
    vendor_ids = (
        vendor_ids if vendor_ids is not None else _order_vendor_ids(db, company_id, order_id)
    )
    queued: list[PushNotification] = []
    for user_id in _eligible_admin_ids(db, company_id, admin_permissions):
        notification = _queue_notification(
            db,
            company_id=company_id,
            recipient_user_id=user_id,
            event_type=event_type,
            event_key=event_key,
            title=title,
            body=body,
            target_route=f"/admin/orders?order_id={order.id}",
            order_id=order.id,
        )
        if notification is not None:
            queued.append(notification)
    for vendor_id in vendor_ids:
        for user_id in _eligible_vendor_ids(db, company_id, vendor_id):
            notification = _queue_notification(
                db,
                company_id=company_id,
                recipient_user_id=user_id,
                event_type=event_type,
                event_key=f"{event_key}:vendor:{vendor_id}",
                title=title,
                body=body,
                target_route=f"/vendor/orders?order_id={order.id}",
                order_id=order.id,
                vendor_id=vendor_id,
            )
            if notification is not None:
                queued.append(notification)
    return queued


def enqueue_order_created(db: Session, *, company_id: str, order: Order) -> list[PushNotification]:
    is_pos_sale = order.sales_channel == "pos" or order.order_source == "pos"
    title = "New POS sale" if is_pos_sale else "New order"
    body = (
        f"POS sale {order.order_number} is complete."
        if is_pos_sale
        else f"New order {order.order_number} is ready for review."
    )
    return enqueue_order_event(
        db,
        company_id=company_id,
        order_id=order.id,
        event_type="order_created",
        event_key=f"order-created:{order.id}",
        title=title,
        body=body,
    )


def enqueue_order_status_changed(
    db: Session,
    *,
    company_id: str,
    order: Order,
    history_id: str,
    previous_status: str,
) -> list[PushNotification]:
    return enqueue_order_event(
        db,
        company_id=company_id,
        order_id=order.id,
        event_type="order_status_changed",
        event_key=f"order-status:{history_id}",
        title="Order status updated",
        body=f"Order {order.order_number} moved from {previous_status} to {order.status}.",
    )


def enqueue_payment_recorded(
    db: Session,
    *,
    company_id: str,
    order: Order,
    payment_id: str,
) -> list[PushNotification]:
    return enqueue_order_event(
        db,
        company_id=company_id,
        order_id=order.id,
        event_type="payment_recorded",
        event_key=f"payment-recorded:{payment_id}",
        title="Payment recorded",
        body=f"A payment was recorded for order {order.order_number}.",
    )


def enqueue_vendor_item_status_changed(
    db: Session,
    *,
    company_id: str,
    order_id: str,
    vendor_id: str,
    history_id: str,
    from_status: str,
    to_status: str,
) -> list[PushNotification]:
    order = db.get(Order, order_id)
    if order is None or order.company_id != company_id:
        return []
    return enqueue_order_event(
        db,
        company_id=company_id,
        order_id=order_id,
        event_type="vendor_item_status_changed",
        event_key=f"vendor-item-status:{history_id}",
        title="Vendor order updated",
        body=f"Order {order.order_number} item moved from {from_status} to {to_status}.",
        vendor_ids={vendor_id},
    )


def enqueue_delivery_event(
    db: Session,
    *,
    company_id: str,
    order_id: str,
    event_type: str,
    event_key: str,
    title: str,
    body: str,
) -> list[PushNotification]:
    return enqueue_order_event(
        db,
        company_id=company_id,
        order_id=order_id,
        event_type=event_type,
        event_key=event_key,
        title=title,
        body=body,
        admin_permissions=("orders.view", "delivery.manage"),
    )


def register_subscription(
    db: Session,
    *,
    company_id: str,
    user_id: str,
    payload: PushSubscriptionCreate,
) -> PushSubscription:
    if not get_settings().effective_push_enabled:
        raise ServiceError(503, "Browser push notifications are not configured.")
    if not payload.endpoint.startswith("https://"):
        raise ServiceError(422, "Push endpoint must use HTTPS.")
    expiration_at = None
    if payload.expiration_time:
        now_ms = int(utcnow().timestamp() * 1000)
        expiration_at = utcnow() + timedelta(milliseconds=payload.expiration_time - now_ms)
    subscription = db.scalar(
        select(PushSubscription).where(
            PushSubscription.company_id == company_id,
            PushSubscription.user_id == user_id,
            PushSubscription.endpoint == payload.endpoint,
        )
    )
    if subscription is None:
        subscription = PushSubscription(
            company_id=company_id,
            user_id=user_id,
            endpoint=payload.endpoint,
            p256dh=payload.keys.p256dh,
            auth=payload.keys.auth,
        )
        db.add(subscription)
    subscription.p256dh = payload.keys.p256dh
    subscription.auth = payload.keys.auth
    subscription.expiration_at = expiration_at
    subscription.user_agent = payload.user_agent
    subscription.device_label = payload.device_label
    subscription.is_active = True
    subscription.last_seen_at = utcnow()
    db.flush()
    db.refresh(subscription)
    return subscription


def list_subscriptions(db: Session, *, company_id: str, user_id: str) -> list[PushSubscription]:
    return list(
        db.scalars(
            select(PushSubscription)
            .where(
                PushSubscription.company_id == company_id,
                PushSubscription.user_id == user_id,
            )
            .order_by(PushSubscription.created_at.desc())
        ).all()
    )


def delete_subscription(
    db: Session,
    *,
    company_id: str,
    user_id: str,
    subscription_id: str,
) -> None:
    subscription = db.scalar(
        select(PushSubscription).where(
            PushSubscription.company_id == company_id,
            PushSubscription.user_id == user_id,
            PushSubscription.id == subscription_id,
        )
    )
    if subscription is None:
        raise ServiceError(404, "Push subscription not found.")
    subscription.is_active = False
    subscription.last_seen_at = utcnow()
    db.flush()


def enqueue_test_notification(db: Session, *, context_user: User) -> PushNotification:
    settings = get_settings()
    if not settings.effective_push_enabled:
        raise ServiceError(503, "Browser push notifications are not configured.")
    route = (
        "/vendor/orders"
        if context_user.company_id and _is_vendor(db, context_user.id)
        else "/admin/orders"
    )
    notification = _queue_notification(
        db,
        company_id=context_user.company_id or "",
        recipient_user_id=context_user.id,
        event_type="push_test",
        event_key=f"push-test:{context_user.id}:{new_uuid()}",
        title="ERP notifications are enabled",
        body="This is a test order notification from your ERP workspace.",
        target_route=route,
    )
    if notification is None:
        raise ServiceError(503, "Browser push notifications are not configured.")
    db.flush()
    return notification


def _is_vendor(db: Session, user_id: str) -> bool:
    return db.scalar(
        select(User.id)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(User.id == user_id, Role.name == "Vendor")
    ) is not None


def send_web_push(subscription: PushSubscription, payload: dict[str, Any]) -> None:
    from pywebpush import webpush

    settings = get_settings()
    webpush(
        subscription_info={
            "endpoint": subscription.endpoint,
            "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
        },
        data=json.dumps(payload, separators=(",", ":")),
        vapid_private_key=settings.push_vapid_private_key,
        vapid_claims={"sub": settings.push_vapid_subject},
        ttl=settings.push_ttl_seconds,
    )


def _push_error_status(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return int(value) if isinstance(value, int) else None


def process_push_notifications(db: Session, *, limit: int = 50) -> dict[str, int]:
    settings = get_settings()
    stats = {"processed": 0, "sent": 0, "skipped": 0, "retried": 0, "failed": 0, "expired": 0}
    if not settings.effective_push_enabled:
        return stats
    now = utcnow()
    notifications = list(
        db.scalars(
            select(PushNotification)
            .where(
                PushNotification.status.in_(("queued", "retry")),
                or_(PushNotification.scheduled_at.is_(None), PushNotification.scheduled_at <= now),
            )
            .order_by(PushNotification.created_at)
            .limit(limit)
        ).all()
    )
    for notification in notifications:
        stats["processed"] += 1
        notification.status = "sending"
        notification.attempts += 1
        db.flush()
        subscriptions = list(
            db.scalars(
                select(PushSubscription).where(
                    PushSubscription.company_id == notification.company_id,
                    PushSubscription.user_id == notification.recipient_user_id,
                    PushSubscription.is_active.is_(True),
                )
            ).all()
        )
        if not subscriptions:
            notification.status = "skipped"
            notification.sent_at = now
            stats["skipped"] += 1
            continue
        payload = {
            "title": notification.title,
            "body": notification.body,
            "data": {
                **notification.payload_json,
                "url": notification.target_route,
            },
        }
        successful = 0
        transient_failures = 0
        errors: list[str] = []
        for subscription in subscriptions:
            try:
                send_web_push(subscription, payload)
            except Exception as exc:  # provider errors must not stop other devices
                status_code = _push_error_status(exc)
                if status_code in {404, 410}:
                    subscription.is_active = False
                    stats["expired"] += 1
                    delivery_status = "expired"
                else:
                    transient_failures += 1
                    delivery_status = "failed"
                message = str(exc)[:2000]
                errors.append(message)
                db.add(
                    PushDeliveryLog(
                        company_id=notification.company_id,
                        notification_id=notification.id,
                        subscription_id=subscription.id,
                        status=delivery_status,
                        adapter=PUSH_ADAPTER,
                        error=message,
                        payload_json={"event_type": notification.event_type},
                    )
                )
                continue
            successful += 1
            subscription.last_seen_at = now
            db.add(
                PushDeliveryLog(
                    company_id=notification.company_id,
                    notification_id=notification.id,
                    subscription_id=subscription.id,
                    status="sent",
                    adapter=PUSH_ADAPTER,
                    payload_json={"event_type": notification.event_type},
                )
            )
        if successful:
            notification.status = "sent"
            notification.sent_at = now
            notification.last_error = "; ".join(errors)[:4000] or None
            stats["sent"] += 1
        elif transient_failures and notification.attempts < settings.push_max_attempts:
            notification.status = "retry"
            notification.scheduled_at = now + timedelta(
                seconds=min(300, 2 ** notification.attempts)
            )
            notification.last_error = "; ".join(errors)[:4000]
            stats["retried"] += 1
        else:
            notification.status = "failed"
            notification.failed_at = now
            notification.last_error = "; ".join(errors)[:4000] or "All push subscriptions expired."
            stats["failed"] += 1
    db.flush()
    return stats
