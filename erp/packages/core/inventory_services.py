from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from erp.packages.core.catalog_services import get_product, require_company_id
from erp.packages.core.db.models import ProductVariant, StockMovement, Warehouse
from erp.packages.core.schemas import StockMovementCreate, WarehouseCreate, WarehouseUpdate
from erp.packages.core.services import ServiceError, record_audit

POSITIVE_MOVEMENTS = {"opening", "stock_in"}
NEGATIVE_MOVEMENTS = {"stock_out", "damaged"}
ADJUSTMENT_MOVEMENT = "adjustment"
ALL_MOVEMENTS = POSITIVE_MOVEMENTS | NEGATIVE_MOVEMENTS | {ADJUSTMENT_MOVEMENT}


@dataclass(frozen=True)
class StockLevel:
    company_id: str
    warehouse_id: str
    product_id: str
    variant_id: str | None
    quantity_on_hand: int


def normalize_warehouse_code(code: str) -> str:
    return code.strip().upper()


def normalize_movement_type(movement_type: str) -> str:
    normalized = movement_type.strip().lower()
    if normalized not in ALL_MOVEMENTS:
        raise ServiceError(422, f"Unsupported stock movement type: {movement_type}.")
    return normalized


def ensure_unique_warehouse_code(
    db: Session,
    *,
    company_id: str,
    code: str,
    exclude_warehouse_id: str | None = None,
) -> None:
    query = select(Warehouse.id).where(Warehouse.company_id == company_id, Warehouse.code == code)
    if exclude_warehouse_id:
        query = query.where(Warehouse.id != exclude_warehouse_id)
    if db.scalar(query):
        raise ServiceError(409, f"Warehouse code already exists: {code}.")


def list_warehouses(
    db: Session,
    company_id: str | None,
    *,
    include_archived: bool = False,
) -> list[Warehouse]:
    scoped_company_id = require_company_id(company_id)
    query = select(Warehouse).where(Warehouse.company_id == scoped_company_id)
    if not include_archived:
        query = query.where(Warehouse.is_active.is_(True))
    return list(db.scalars(query.order_by(Warehouse.code)).all())


def get_warehouse(db: Session, company_id: str | None, warehouse_id: str) -> Warehouse:
    scoped_company_id = require_company_id(company_id)
    warehouse = db.scalar(
        select(Warehouse).where(
            Warehouse.company_id == scoped_company_id,
            Warehouse.id == warehouse_id,
        )
    )
    if warehouse is None:
        raise ServiceError(404, "Warehouse not found.")
    return warehouse


def create_warehouse(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    payload: WarehouseCreate,
) -> Warehouse:
    scoped_company_id = require_company_id(company_id)
    code = normalize_warehouse_code(payload.code)
    ensure_unique_warehouse_code(db, company_id=scoped_company_id, code=code)
    warehouse = Warehouse(
        company_id=scoped_company_id,
        code=code,
        name=payload.name,
        address=payload.address,
        is_active=True,
    )
    db.add(warehouse)
    db.flush()
    db.refresh(warehouse)
    record_audit(
        db,
        action="inventory.warehouse_created",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="warehouse",
        entity_id=warehouse.id,
        metadata={"code": warehouse.code, "name": warehouse.name},
    )
    return warehouse


def update_warehouse(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    warehouse_id: str,
    payload: WarehouseUpdate,
) -> Warehouse:
    scoped_company_id = require_company_id(company_id)
    warehouse = get_warehouse(db, scoped_company_id, warehouse_id)
    fields = payload.model_dump(exclude_unset=True)
    if "code" in fields and fields["code"] is not None:
        fields["code"] = normalize_warehouse_code(fields["code"])
        ensure_unique_warehouse_code(
            db,
            company_id=scoped_company_id,
            code=fields["code"],
            exclude_warehouse_id=warehouse.id,
        )
    for field in ("code", "name", "address", "is_active"):
        if field in fields:
            setattr(warehouse, field, fields[field])
    db.flush()
    db.refresh(warehouse)
    record_audit(
        db,
        action="inventory.warehouse_updated",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="warehouse",
        entity_id=warehouse.id,
        metadata={"updated_fields": sorted(fields)},
    )
    return warehouse


def archive_warehouse(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    warehouse_id: str,
) -> None:
    scoped_company_id = require_company_id(company_id)
    warehouse = get_warehouse(db, scoped_company_id, warehouse_id)
    warehouse.is_active = False
    record_audit(
        db,
        action="inventory.warehouse_deleted",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="warehouse",
        entity_id=warehouse.id,
        metadata={"soft_delete": True},
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
        raise ServiceError(409, "Cannot move stock for an inactive product variant.")
    return variant


def current_stock(
    db: Session,
    *,
    company_id: str,
    warehouse_id: str,
    product_id: str,
    variant_id: str | None,
) -> int:
    query = select(func.coalesce(func.sum(StockMovement.quantity_delta), 0)).where(
        StockMovement.company_id == company_id,
        StockMovement.warehouse_id == warehouse_id,
        StockMovement.product_id == product_id,
    )
    if variant_id is None:
        query = query.where(StockMovement.variant_id.is_(None))
    else:
        query = query.where(StockMovement.variant_id == variant_id)
    return int(db.scalar(query) or 0)


def movement_delta(payload: StockMovementCreate) -> tuple[str, int]:
    movement_type = normalize_movement_type(payload.movement_type)
    if movement_type == ADJUSTMENT_MOVEMENT:
        if payload.quantity_delta is None or payload.quantity_delta == 0:
            raise ServiceError(422, "Adjustment requires a non-zero quantity_delta.")
        if payload.quantity is not None:
            raise ServiceError(422, "Adjustment must use quantity_delta, not quantity.")
        return movement_type, payload.quantity_delta

    if payload.quantity is None:
        raise ServiceError(422, f"{movement_type} requires quantity.")
    if payload.quantity_delta is not None:
        raise ServiceError(422, f"{movement_type} must use quantity, not quantity_delta.")
    if movement_type in POSITIVE_MOVEMENTS:
        return movement_type, payload.quantity
    return movement_type, -payload.quantity


def list_stock_movements(
    db: Session,
    company_id: str | None,
    *,
    warehouse_id: str | None = None,
    product_id: str | None = None,
) -> list[StockMovement]:
    scoped_company_id = require_company_id(company_id)
    query = select(StockMovement).where(StockMovement.company_id == scoped_company_id)
    if warehouse_id:
        query = query.where(StockMovement.warehouse_id == warehouse_id)
    if product_id:
        query = query.where(StockMovement.product_id == product_id)
    return list(db.scalars(query.order_by(StockMovement.created_at.desc())).all())


def record_stock_movement(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    payload: StockMovementCreate,
) -> StockMovement:
    scoped_company_id = require_company_id(company_id)
    warehouse = get_warehouse(db, scoped_company_id, payload.warehouse_id)
    if not warehouse.is_active:
        raise ServiceError(409, "Cannot move stock in an inactive warehouse.")
    product = get_product(db, scoped_company_id, payload.product_id)
    if product.status == "archived":
        raise ServiceError(409, "Cannot move stock for an archived product.")
    get_variant(
        db,
        company_id=scoped_company_id,
        product_id=product.id,
        variant_id=payload.variant_id,
    )
    movement_type, delta = movement_delta(payload)
    before_quantity = current_stock(
        db,
        company_id=scoped_company_id,
        warehouse_id=warehouse.id,
        product_id=product.id,
        variant_id=payload.variant_id,
    )
    after_quantity = before_quantity + delta
    if after_quantity < 0:
        raise ServiceError(409, "Stock movement would make available stock negative.")

    movement_fields = {
        "company_id": scoped_company_id,
        "warehouse_id": warehouse.id,
        "product_id": product.id,
        "variant_id": payload.variant_id,
        "movement_type": movement_type,
        "quantity_delta": delta,
        "reference_type": payload.reference_type,
        "reference_id": payload.reference_id,
        "reason": payload.reason,
        "metadata_json": payload.metadata,
        "created_by_id": user_id,
    }
    if payload.occurred_at is not None:
        movement_fields["occurred_at"] = payload.occurred_at
    movement = StockMovement(**movement_fields)
    db.add(movement)
    db.flush()
    db.refresh(movement)
    record_audit(
        db,
        action="inventory.stock_movement_recorded",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="stock_movement",
        entity_id=movement.id,
        metadata={
            "movement_type": movement.movement_type,
            "quantity_delta": movement.quantity_delta,
            "product_id": movement.product_id,
            "warehouse_id": movement.warehouse_id,
        },
    )
    return movement


def stock_levels(
    db: Session,
    company_id: str | None,
    *,
    warehouse_id: str | None = None,
    product_id: str | None = None,
    variant_id: str | None = None,
) -> list[StockLevel]:
    scoped_company_id = require_company_id(company_id)
    query = (
        select(
            StockMovement.company_id,
            StockMovement.warehouse_id,
            StockMovement.product_id,
            StockMovement.variant_id,
            func.coalesce(func.sum(StockMovement.quantity_delta), 0).label("quantity_on_hand"),
        )
        .where(StockMovement.company_id == scoped_company_id)
        .group_by(
            StockMovement.company_id,
            StockMovement.warehouse_id,
            StockMovement.product_id,
            StockMovement.variant_id,
        )
        .order_by(StockMovement.warehouse_id, StockMovement.product_id)
    )
    if warehouse_id:
        query = query.where(StockMovement.warehouse_id == warehouse_id)
    if product_id:
        query = query.where(StockMovement.product_id == product_id)
    if variant_id:
        query = query.where(StockMovement.variant_id == variant_id)

    return [
        StockLevel(
            company_id=row.company_id,
            warehouse_id=row.warehouse_id,
            product_id=row.product_id,
            variant_id=row.variant_id,
            quantity_on_hand=int(row.quantity_on_hand),
        )
        for row in db.execute(query)
    ]
