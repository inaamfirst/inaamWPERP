"""inventory foundation

Revision ID: 202607010004
Revises: 202607010003
Create Date: 2026-07-01 00:00:03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "202607010004"
down_revision = "202607010003"
branch_labels = None
depends_on = None

UUID = sa.String(length=36)
SHORT = sa.String(length=40)
MEDIUM = sa.String(length=120)
LONG = sa.String(length=255)
JSON = sa.JSON()
NOW = sa.text("CURRENT_TIMESTAMP")


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "warehouses",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("code", SHORT, nullable=False),
        sa.Column("name", LONG, nullable=False),
        sa.Column("address", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *timestamps(),
        sa.UniqueConstraint("company_id", "code"),
    )
    op.create_index("ix_warehouses_company_id", "warehouses", ["company_id"])

    op.create_table(
        "stock_movements",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("warehouse_id", UUID, sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("product_id", UUID, sa.ForeignKey("products.id"), nullable=False),
        sa.Column("variant_id", UUID, sa.ForeignKey("product_variants.id")),
        sa.Column("movement_type", SHORT, nullable=False),
        sa.Column("quantity_delta", sa.Integer(), nullable=False),
        sa.Column("reference_type", sa.String(length=80)),
        sa.Column("reference_id", MEDIUM),
        sa.Column("transfer_group_id", UUID),
        sa.Column("reason", sa.Text()),
        sa.Column("metadata", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_by_id", UUID, sa.ForeignKey("users.id")),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        *timestamps(),
    )
    op.create_index(
        "ix_stock_movements_stock_lookup",
        "stock_movements",
        ["company_id", "warehouse_id", "product_id", "variant_id"],
    )
    op.create_index(
        "ix_stock_movements_product",
        "stock_movements",
        ["company_id", "product_id", "variant_id"],
    )
    op.create_index(
        "ix_stock_movements_reference",
        "stock_movements",
        ["company_id", "reference_type", "reference_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_stock_movements_reference", table_name="stock_movements")
    op.drop_index("ix_stock_movements_product", table_name="stock_movements")
    op.drop_index("ix_stock_movements_stock_lookup", table_name="stock_movements")
    op.drop_table("stock_movements")
    op.drop_index("ix_warehouses_company_id", table_name="warehouses")
    op.drop_table("warehouses")
