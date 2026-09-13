from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from erp.packages.core.api.dependencies import (
    CurrentContext,
    DbSession,
    require_any_permission,
    service_error_to_http,
)
from erp.packages.core.config import get_settings
from erp.packages.core.production_services import read_worker_heartbeat
from erp.packages.core.push_services import (
    delete_subscription,
    enqueue_test_notification,
    list_subscriptions,
    push_notification_out,
    push_subscription_out,
    register_subscription,
)
from erp.packages.core.schemas import (
    PushConfigOut,
    PushNotificationOut,
    PushSubscriptionCreate,
    PushSubscriptionOut,
)
from erp.packages.core.services import AuthContext, ServiceError

router = APIRouter()
PushContext = Annotated[
    AuthContext,
    Depends(require_any_permission("orders.view", "vendor.orders.view")),
]


@router.get("/push/config", response_model=PushConfigOut, tags=["push"])
def push_config(context: CurrentContext) -> PushConfigOut:
    settings = get_settings()
    heartbeat = read_worker_heartbeat()
    enabled = bool(context.user.company_id and settings.effective_push_enabled)
    worker_status = str(heartbeat.get("status")) if heartbeat and heartbeat.get("status") else None
    worker_updated_at = str(heartbeat.get("updated_at")) if heartbeat and heartbeat.get("updated_at") else None
    if not enabled:
        detail = "Browser push needs ERP_PUSH_ENABLED and valid VAPID keys on the server."
    elif heartbeat is None:
        detail = "The ERP worker heartbeat is missing. Start the worker to deliver queued notifications."
    else:
        detail = f"Worker is {worker_status or 'active'} and can deliver queued notifications."
    return PushConfigOut(
        enabled=enabled,
        public_key=settings.push_vapid_public_key if settings.effective_push_enabled else None,
        worker_available=heartbeat is not None,
        worker_status=worker_status,
        worker_updated_at=worker_updated_at,
        readiness_detail=detail,
    )


@router.get(
    "/push/subscriptions",
    response_model=list[PushSubscriptionOut],
    tags=["push"],
)
def push_subscriptions(context: PushContext, db: DbSession) -> list[PushSubscriptionOut]:
    if not context.user.company_id:
        return []
    return [
        PushSubscriptionOut.model_validate(push_subscription_out(subscription))
        for subscription in list_subscriptions(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
        )
    ]


@router.post(
    "/push/subscriptions",
    response_model=PushSubscriptionOut,
    status_code=201,
    tags=["push"],
)
def create_push_subscription(
    payload: PushSubscriptionCreate,
    context: PushContext,
    db: DbSession,
) -> PushSubscriptionOut:
    if not context.user.company_id:
        raise service_error_to_http(ServiceError(403, "A company-scoped user is required."))
    try:
        subscription = register_subscription(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            payload=payload,
        )
        db.commit()
        return PushSubscriptionOut.model_validate(push_subscription_out(subscription))
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.delete("/push/subscriptions/{subscription_id}", status_code=204, tags=["push"])
def remove_push_subscription(
    subscription_id: str,
    context: PushContext,
    db: DbSession,
) -> Response:
    if not context.user.company_id:
        return Response(status_code=204)
    try:
        delete_subscription(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            subscription_id=subscription_id,
        )
        db.commit()
        return Response(status_code=204)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.post(
    "/push/test",
    response_model=PushNotificationOut,
    status_code=202,
    tags=["push"],
)
def test_push(context: PushContext, db: DbSession) -> PushNotificationOut:
    if not context.user.company_id:
        raise service_error_to_http(ServiceError(403, "A company-scoped user is required."))
    try:
        notification = enqueue_test_notification(db, context_user=context.user)
        db.commit()
        return PushNotificationOut.model_validate(push_notification_out(notification))
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc
