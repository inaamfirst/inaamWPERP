from __future__ import annotations

import csv
from dataclasses import dataclass
from io import StringIO

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from erp.packages.core.catalog_services import require_company_id
from erp.packages.core.db.models import Customer, Order, Product, StockMovement

REVENUE_STATUSES = {"pending", "confirmed", "packing", "ready", "dispatched", "delivered"}


@dataclass(frozen=True)
class DashboardSummary:
    sales_count: int
    revenue_minor: int
    pending_orders: int
    low_stock_count: int
    customer_count: int
    product_count: int


@dataclass(frozen=True)
class SalesReportItem:
    status: str
    order_count: int
    revenue_minor: int


@dataclass(frozen=True)
class InventoryReportItem:
    product_id: str
    variant_id: str | None
    warehouse_id: str | None
    quantity_on_hand: int


def order_revenue_filter(company_id: str):
    return Order.company_id == company_id, Order.status.in_(REVENUE_STATUSES)


def product_count(db: Session, company_id: str) -> int:
    return int(
        db.scalar(
            select(func.count(Product.id)).where(
                Product.company_id == company_id,
                Product.status != "archived",
            )
        )
        or 0
    )


def customer_count(db: Session, company_id: str) -> int:
    return int(
        db.scalar(
            select(func.count(Customer.id)).where(
                Customer.company_id == company_id,
                Customer.status != "archived",
            )
        )
        or 0
    )


def sales_count(db: Session, company_id: str) -> int:
    return int(
        db.scalar(select(func.count(Order.id)).where(*order_revenue_filter(company_id))) or 0
    )


def revenue_minor(db: Session, company_id: str) -> int:
    return int(
        db.scalar(
            select(func.coalesce(func.sum(Order.total_minor), 0)).where(
                *order_revenue_filter(company_id)
            )
        )
        or 0
    )


def pending_order_count(db: Session, company_id: str) -> int:
    return int(
        db.scalar(
            select(func.count(Order.id)).where(
                Order.company_id == company_id,
                Order.status == "pending",
            )
        )
        or 0
    )


def product_stock_totals(db: Session, company_id: str) -> dict[str, int]:
    rows = db.execute(
        select(
            StockMovement.product_id,
            func.coalesce(func.sum(StockMovement.quantity_delta), 0).label("quantity"),
        )
        .where(StockMovement.company_id == company_id)
        .group_by(StockMovement.product_id)
    )
    return {str(row.product_id): int(row.quantity) for row in rows}


def low_stock_count(db: Session, company_id: str) -> int:
    active_product_ids = list(
        db.scalars(
            select(Product.id).where(
                Product.company_id == company_id,
                Product.status != "archived",
            )
        ).all()
    )
    stock_totals = product_stock_totals(db, company_id)
    return sum(1 for product_id in active_product_ids if stock_totals.get(product_id, 0) <= 0)


def dashboard_summary(db: Session, company_id: str | None) -> DashboardSummary:
    scoped_company_id = require_company_id(company_id)
    return DashboardSummary(
        sales_count=sales_count(db, scoped_company_id),
        revenue_minor=revenue_minor(db, scoped_company_id),
        pending_orders=pending_order_count(db, scoped_company_id),
        low_stock_count=low_stock_count(db, scoped_company_id),
        customer_count=customer_count(db, scoped_company_id),
        product_count=product_count(db, scoped_company_id),
    )


def sales_report(db: Session, company_id: str | None) -> list[SalesReportItem]:
    scoped_company_id = require_company_id(company_id)
    rows = db.execute(
        select(
            Order.status,
            func.count(Order.id).label("order_count"),
            func.coalesce(func.sum(Order.total_minor), 0).label("revenue_minor"),
        )
        .where(Order.company_id == scoped_company_id)
        .group_by(Order.status)
        .order_by(Order.status)
    )
    return [
        SalesReportItem(
            status=str(row.status),
            order_count=int(row.order_count),
            revenue_minor=int(row.revenue_minor),
        )
        for row in rows
    ]


def inventory_report(db: Session, company_id: str | None) -> list[InventoryReportItem]:
    scoped_company_id = require_company_id(company_id)
    rows = db.execute(
        select(
            StockMovement.product_id,
            StockMovement.variant_id,
            StockMovement.warehouse_id,
            func.coalesce(func.sum(StockMovement.quantity_delta), 0).label("quantity_on_hand"),
        )
        .where(StockMovement.company_id == scoped_company_id)
        .group_by(
            StockMovement.product_id,
            StockMovement.variant_id,
            StockMovement.warehouse_id,
        )
        .order_by(StockMovement.product_id)
    )
    return [
        InventoryReportItem(
            product_id=str(row.product_id),
            variant_id=row.variant_id,
            warehouse_id=row.warehouse_id,
            quantity_on_hand=int(row.quantity_on_hand),
        )
        for row in rows
    ]


def customer_report(db: Session, company_id: str | None) -> list[Customer]:
    scoped_company_id = require_company_id(company_id)
    return list(
        db.scalars(
            select(Customer)
            .where(Customer.company_id == scoped_company_id)
            .order_by(Customer.full_name)
        ).all()
    )


def order_report(db: Session, company_id: str | None) -> list[Order]:
    scoped_company_id = require_company_id(company_id)
    return list(
        db.scalars(
            select(Order)
            .where(Order.company_id == scoped_company_id)
            .order_by(Order.created_at.desc())
        ).all()
    )


def orders_csv(db: Session, company_id: str | None) -> str:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "order_number",
            "customer_id",
            "status",
            "total_minor",
            "paid_minor",
            "payment_status",
            "created_at",
        ]
    )
    for order in order_report(db, company_id):
        writer.writerow(
            [
                order.order_number,
                order.customer_id,
                order.status,
                order.total_minor,
                order.paid_minor,
                order.payment_status,
                order.created_at.isoformat(),
            ]
        )
    return output.getvalue()
