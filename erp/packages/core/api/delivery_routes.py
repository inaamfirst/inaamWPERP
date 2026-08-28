from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from erp.packages.core import delivery_services
from erp.packages.core.api.dependencies import DbSession, require_permission, service_error_to_http
from erp.packages.core.db.models import Customer, User
from erp.packages.core.schemas import (
    DeliveryAssignmentCreate,
    DeliveryAssignmentOut,
    DeliveryAssignmentUpdate,
    DeliveryRiderOut,
    DeliveryStatusChange,
)
from erp.packages.core.services import AuthContext, ServiceError, user_role_names

router = APIRouter()

AdminDeliveryContext = Annotated[AuthContext, Depends(require_permission("delivery.manage"))]
RiderDeliveryContext = Annotated[
    AuthContext, Depends(require_permission("delivery.view_assigned"))
]
RiderUpdateContext = Annotated[
    AuthContext, Depends(require_permission("delivery.update_assigned"))
]


def _rider_id(db, context: AuthContext) -> str:
    if "Rider" not in user_role_names(db, context.user.id):
        raise ServiceError(403, "A Rider role is required for delivery access.")
    if not context.user.company_id:
        raise ServiceError(403, "A company-scoped user is required.")
    return context.user.id


def _rider_out(user: User) -> DeliveryRiderOut:
    return DeliveryRiderOut(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        is_active=user.is_active,
    )


@router.get("/delivery/admin/summary", response_model=dict[str, int], tags=["delivery"])
def admin_delivery_summary(context: AdminDeliveryContext, db: DbSession) -> dict[str, int]:
    return delivery_services.dashboard_summary(db, context.user.company_id)


@router.get("/delivery/admin/riders", response_model=list[DeliveryRiderOut], tags=["delivery"])
def admin_delivery_riders(
    context: AdminDeliveryContext, db: DbSession
) -> list[DeliveryRiderOut]:
    return [_rider_out(user) for user in delivery_services.list_riders(db, context.user.company_id)]


@router.get(
    "/delivery/admin/unassigned",
    response_model=list[dict[str, object]],
    tags=["delivery"],
)
def admin_unassigned_deliveries(
    context: AdminDeliveryContext, db: DbSession
) -> list[dict[str, object]]:
    orders = delivery_services.unassigned_orders(db, context.user.company_id)
    result: list[dict[str, object]] = []
    for order in orders:
        customer = db.get(Customer, order.customer_id)
        result.append(
            {
                "id": order.id,
                "order_number": order.order_number,
                "status": order.status,
                "total_minor": order.total_minor,
                "payment_status": order.payment_status,
                "customer_name": customer.full_name if customer else None,
                "customer_phone": customer.phone if customer else None,
                "created_at": order.created_at,
            }
        )
    return result


@router.get(
    "/delivery/admin/assignments",
    response_model=list[DeliveryAssignmentOut],
    tags=["delivery"],
)
def admin_delivery_assignments(
    context: AdminDeliveryContext,
    db: DbSession,
    status: str | None = Query(default=None),
) -> list[DeliveryAssignmentOut]:
    try:
        return [
            DeliveryAssignmentOut.model_validate(
                delivery_services.assignment_out(db, row), from_attributes=True
            )
            for row in delivery_services.list_assignments(
                db, context.user.company_id, status=status
            )
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.post(
    "/delivery/admin/assignments",
    response_model=DeliveryAssignmentOut,
    status_code=201,
    tags=["delivery"],
)
def create_delivery_assignment(
    payload: DeliveryAssignmentCreate,
    context: AdminDeliveryContext,
    db: DbSession,
) -> DeliveryAssignmentOut:
    try:
        row = delivery_services.create_assignment(
            db,
            company_id=context.user.company_id,
            admin_user_id=context.user.id,
            order_id=payload.order_id,
            rider_user_id=payload.rider_user_id,
        )
        db.commit()
        return DeliveryAssignmentOut.model_validate(
            delivery_services.assignment_out(db, row), from_attributes=True
        )
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.put(
    "/delivery/admin/assignments/{assignment_id}",
    response_model=DeliveryAssignmentOut,
    tags=["delivery"],
)
def reassign_delivery(
    assignment_id: str,
    payload: DeliveryAssignmentUpdate,
    context: AdminDeliveryContext,
    db: DbSession,
) -> DeliveryAssignmentOut:
    try:
        row = delivery_services.reassign_assignment(
            db,
            company_id=context.user.company_id,
            admin_user_id=context.user.id,
            assignment_id=assignment_id,
            rider_user_id=payload.rider_user_id,
        )
        db.commit()
        return DeliveryAssignmentOut.model_validate(
            delivery_services.assignment_out(db, row), from_attributes=True
        )
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get(
    "/delivery/rider/dashboard",
    response_model=dict[str, object],
    tags=["delivery"],
)
def rider_delivery_dashboard(
    context: RiderDeliveryContext, db: DbSession
) -> dict[str, object]:
    try:
        rider_id = _rider_id(db, context)
        rows = delivery_services.list_assignments(
            db, context.user.company_id, rider_user_id=rider_id
        )
        return {
            "summary": delivery_services.dashboard_summary(
                db, context.user.company_id, rider_user_id=rider_id
            ),
            "assignments": [delivery_services.assignment_out(db, row) for row in rows],
        }
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.get(
    "/delivery/rider/assignments",
    response_model=list[DeliveryAssignmentOut],
    tags=["delivery"],
)
def rider_delivery_assignments(
    context: RiderDeliveryContext,
    db: DbSession,
    status: str | None = Query(default=None),
) -> list[DeliveryAssignmentOut]:
    try:
        rider_id = _rider_id(db, context)
        return [
            DeliveryAssignmentOut.model_validate(
                delivery_services.assignment_out(db, row), from_attributes=True
            )
            for row in delivery_services.list_assignments(
                db, context.user.company_id, rider_user_id=rider_id, status=status
            )
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.post(
    "/delivery/rider/assignments/{assignment_id}/status",
    response_model=DeliveryAssignmentOut,
    tags=["delivery"],
)
def update_rider_delivery_status(
    assignment_id: str,
    payload: DeliveryStatusChange,
    context: RiderUpdateContext,
    db: DbSession,
) -> DeliveryAssignmentOut:
    try:
        rider_id = _rider_id(db, context)
        row = delivery_services.change_assignment_status(
            db,
            company_id=context.user.company_id,
            rider_user_id=rider_id,
            assignment_id=assignment_id,
            status=payload.status,
            reason=payload.reason,
        )
        db.commit()
        return DeliveryAssignmentOut.model_validate(
            delivery_services.assignment_out(db, row), from_attributes=True
        )
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc
