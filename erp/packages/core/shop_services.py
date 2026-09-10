from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from erp.packages.core.catalog_services import get_product, require_company_id
from erp.packages.core.db.models import (
    ShopFinanceEntry,
    ShopPurchase,
    ShopPurchaseLine,
    ShopSupplier,
    Warehouse,
)
from erp.packages.core.inventory_services import record_stock_movement
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
        if product.vendor_id != vendor_id:
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
    return {
        "purchase_total_minor": sum(row.total_minor for row in purchases),
        "supplier_payable_minor": sum(row.total_minor - row.paid_minor for row in purchases),
        "cash_in_minor": sum(row.amount_minor for row in finance if row.direction == "in"),
        "cash_out_minor": sum(row.amount_minor for row in finance if row.direction == "out"),
        "currency": "PKR",
    }