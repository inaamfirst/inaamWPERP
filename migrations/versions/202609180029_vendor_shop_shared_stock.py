"""Classify sales channels and reconcile remaining WooCommerce stock to vendor shops.

Revision ID: 202609180029
Revises: 202609100028
"""

from __future__ import annotations

import hashlib
import uuid

import sqlalchemy as sa
from alembic import op


revision = "202609180029"
down_revision = "202609100028"
branch_labels = None
depends_on = None


def _stock_total(bind: sa.Connection, movements: sa.Table, *, company_id: str, warehouse_id: str, product_id: str, variant_id: str | None) -> int:
    statement = sa.select(sa.func.coalesce(sa.func.sum(movements.c.quantity_delta), 0)).where(
        movements.c.company_id == company_id,
        movements.c.warehouse_id == warehouse_id,
        movements.c.product_id == product_id,
    )
    statement = statement.where(movements.c.variant_id.is_(None) if variant_id is None else movements.c.variant_id == variant_id)
    return int(bind.execute(statement).scalar() or 0)


def _audit_once(
    bind: sa.Connection,
    audits: sa.Table,
    *,
    company_id: str,
    action: str,
    entity_type: str,
    entity_id: str,
    metadata: dict[str, object],
) -> None:
    # AuditLog.entity_id is VARCHAR(120), while a Woo baseline reference can
    # contain three UUIDs and exceed that limit. Keep a stable, short key for
    # idempotency and retain the original reference in JSON metadata.
    if len(entity_id) > 120:
        metadata = {**metadata, "reference_id": entity_id}
        entity_id = f"sha256:{hashlib.sha256(entity_id.encode('utf-8')).hexdigest()}"
    exists = bind.execute(
        sa.select(audits.c.id).where(
            audits.c.company_id == company_id,
            audits.c.action == action,
            audits.c.entity_type == entity_type,
            audits.c.entity_id == entity_id,
        )
    ).scalar()
    if exists is None:
        bind.execute(sa.insert(audits).values(
            id=str(uuid.uuid4()), company_id=company_id, action=action,
            entity_type=entity_type, entity_id=entity_id, metadata=metadata,
        ))


def upgrade() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    orders = sa.Table("orders", metadata, autoload_with=bind)
    products = sa.Table("products", metadata, autoload_with=bind)
    vendor_products = sa.Table("vendor_products", metadata, autoload_with=bind)
    warehouses = sa.Table("warehouses", metadata, autoload_with=bind)
    movements = sa.Table("stock_movements", metadata, autoload_with=bind)
    maps = sa.Table("external_resource_map", metadata, autoload_with=bind)
    audits = sa.Table("audit_logs", metadata, autoload_with=bind)

    # POS orders were already deducted from Shop stock. Label them explicitly.
    bind.execute(
        orders.update()
        .where(sa.or_(orders.c.sales_channel == "pos", orders.c.order_source == "pos"))
        .values(sales_channel="pos", order_source="pos")
    )
    # Some early POS rows predate the channel fields. Their stock movements
    # are the durable POS source marker, so classify those rows as well.
    pos_order_rows = bind.execute(
        sa.select(movements.c.company_id, movements.c.reference_id).where(
            movements.c.reference_type == "pos_sale",
            movements.c.reference_id.is_not(None),
        ).distinct()
    ).all()
    for company_id, order_id in pos_order_rows:
        bind.execute(
            orders.update().where(
                orders.c.company_id == company_id,
                orders.c.id == order_id,
            ).values(sales_channel="pos", order_source="pos", reservation_status="deducted")
        )

    # Existing mapped WooCommerce orders are historical: their remaining WOO balance
    # is the baseline, so mark them as such instead of deducting them a second time.
    mapped_orders = bind.execute(
        sa.select(maps.c.company_id, maps.c.internal_resource_id, maps.c.external_resource_id).where(
            maps.c.connector == "woocommerce",
            maps.c.internal_resource_type == "order",
        )
    ).all()
    for company_id, order_id, external_id in mapped_orders:
        bind.execute(
            orders.update().where(
                orders.c.company_id == company_id,
                orders.c.id == order_id,
            ).values(
                sales_channel="woocommerce",
                order_source="woocommerce",
                external_order_id=external_id,
                reservation_status="baseline",
            )
        )
    bind.execute(
        orders.update()
        .where(orders.c.order_source == "woocommerce", orders.c.reservation_status.in_(("none", "reserved")))
        .values(sales_channel="woocommerce", reservation_status="baseline")
    )

    woo_rows = bind.execute(
        sa.select(warehouses.c.id, warehouses.c.company_id).where(warehouses.c.code == "WOO")
    ).all()
    for woo_warehouse_id, company_id in woo_rows:
        balances = bind.execute(
            sa.select(
                movements.c.product_id,
                movements.c.variant_id,
                sa.func.coalesce(sa.func.sum(movements.c.quantity_delta), 0).label("quantity"),
            ).where(
                movements.c.company_id == company_id,
                movements.c.warehouse_id == woo_warehouse_id,
            ).group_by(movements.c.product_id, movements.c.variant_id)
        ).all()
        for product_id, variant_id, quantity in balances:
            quantity = int(quantity or 0)
            if quantity <= 0:
                continue
            product = bind.execute(
                sa.select(products.c.id, products.c.vendor_id).where(
                    products.c.company_id == company_id, products.c.id == product_id
                )
            ).first()
            if product is None:
                continue
            candidates = {product.vendor_id} if product.vendor_id else set()
            candidates.update(bind.execute(
                sa.select(vendor_products.c.vendor_id).where(
                    vendor_products.c.company_id == company_id,
                    vendor_products.c.product_id == product_id,
                )
            ).scalars().all())
            ref_id = f"woo-baseline:{woo_warehouse_id}:{product_id}:{variant_id or 'base'}"
            if len(candidates) != 1:
                _audit_once(
                    bind, audits, company_id=company_id,
                    action="commerce.vendor_stock_reconciliation_ambiguous",
                    entity_type="stock_baseline", entity_id=ref_id,
                    metadata={"warehouse_id": woo_warehouse_id, "product_id": product_id, "variant_id": variant_id, "quantity": quantity, "vendor_ids": sorted(candidates)},
                )
                continue
            vendor_id = next(iter(candidates))
            shop_warehouse_id = bind.execute(
                sa.select(warehouses.c.id).where(
                    warehouses.c.company_id == company_id,
                    warehouses.c.vendor_id == vendor_id,
                    warehouses.c.warehouse_type == "vendor_shop",
                )
            ).scalar()
            if shop_warehouse_id is None:
                shop_warehouse_id = str(uuid.uuid4())
                bind.execute(sa.insert(warehouses).values(
                    id=shop_warehouse_id, company_id=company_id, vendor_id=vendor_id,
                    warehouse_type="vendor_shop", code=f"SHOP-{vendor_id.replace('-', '')[:20]}".upper(),
                    name="Vendor Shop", is_active=True,
                ))
            already_transferred = bind.execute(
                sa.select(movements.c.id).where(
                    movements.c.company_id == company_id,
                    movements.c.warehouse_id == shop_warehouse_id,
                    movements.c.reference_type == "vendor_shop_baseline_transfer",
                    movements.c.reference_id == ref_id,
                )
            ).scalar()
            if already_transferred is not None:
                continue
            group_id = str(uuid.uuid4())
            movement_metadata = {"source_warehouse_id": woo_warehouse_id, "vendor_id": vendor_id, "historical_baseline": True}
            common = {
                "company_id": company_id, "product_id": product_id, "variant_id": variant_id,
                "movement_type": "transfer", "reference_type": "vendor_shop_baseline_transfer",
                "reference_id": ref_id, "transfer_group_id": group_id,
                "reason": "Move remaining WooCommerce stock to the vendor's Shop balance.",
                "metadata": movement_metadata,
            }
            bind.execute(sa.insert(movements).values(id=str(uuid.uuid4()), warehouse_id=woo_warehouse_id, quantity_delta=-quantity, **common))
            bind.execute(sa.insert(movements).values(id=str(uuid.uuid4()), warehouse_id=shop_warehouse_id, quantity_delta=quantity, **common))
            if variant_id is None:
                final_quantity = _stock_total(
                    bind, movements, company_id=company_id, warehouse_id=shop_warehouse_id,
                    product_id=product_id, variant_id=None,
                )
                bind.execute(
                    products.update().where(products.c.id == product_id).values(
                        manage_stock=True,
                        stock_quantity=final_quantity,
                        stock_status="instock" if final_quantity > 0 else "outofstock",
                    )
                )
            _audit_once(
                bind, audits, company_id=company_id,
                action="commerce.vendor_shop_stock_baseline_transferred",
                entity_type="stock_baseline", entity_id=ref_id,
                metadata={"vendor_id": vendor_id, "product_id": product_id, "variant_id": variant_id, "quantity": quantity, "source_warehouse_id": woo_warehouse_id, "shop_warehouse_id": shop_warehouse_id},
            )


def downgrade() -> None:
    # This is an audited data reconciliation. Reversing it automatically could
    # overwrite post-deployment sales, purchases, and adjustments.
    pass
