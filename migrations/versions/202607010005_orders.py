"""orders foundation

Revision ID: 202607010005
Revises: 202607010004
Create Date: 2026-07-01 00:00:04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "202607010005"
down_revision = "202607010004"
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
        "orders",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("customer_id", UUID, sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("order_number", sa.String(length=80), nullable=False),
        sa.Column("status", SHORT, nullable=False, server_default="pending"),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="PKR"),
        sa.Column("subtotal_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("discount_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tax_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("shipping_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("paid_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payment_status", SHORT, nullable=False, server_default="unpaid"),
        sa.Column("notes", sa.Text()),
        sa.Column("metadata", JSON, nullable=False, server_default=sa.text("'{}'")),
        *timestamps(),
        sa.UniqueConstraint("company_id", "order_number"),
    )
    op.create_index("ix_orders_company_id_status", "orders", ["company_id", "status"])
    op.create_index("ix_orders_company_id_customer_id", "orders", ["company_id", "customer_id"])

    op.create_table(
        "order_items",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("order_id", UUID, sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("product_id", UUID, sa.ForeignKey("products.id"), nullable=False),
        sa.Column("variant_id", UUID, sa.ForeignKey("product_variants.id")),
        sa.Column("sku", MEDIUM),
        sa.Column("name", LONG, nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price_minor", sa.Integer(), nullable=False),
        sa.Column("line_total_minor", sa.Integer(), nullable=False),
        sa.Column("metadata", JSON, nullable=False, server_default=sa.text("'{}'")),
        *timestamps(),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])
    op.create_index("ix_order_items_product", "order_items", ["company_id", "product_id"])

    op.create_table(
        "order_status_history",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("order_id", UUID, sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("from_status", SHORT),
        sa.Column("to_status", SHORT, nullable=False),
        sa.Column("changed_by_id", UUID, sa.ForeignKey("users.id")),
        sa.Column("reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )
    op.create_index(
        "ix_order_status_history_order_id",
        "order_status_history",
        ["order_id", "created_at"],
    )

    op.create_table(
        "payments",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("order_id", UUID, sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="PKR"),
        sa.Column("method", sa.String(length=80), nullable=False),
        sa.Column("status", SHORT, nullable=False, server_default="paid"),
        sa.Column("reference", sa.String(length=160)),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("metadata", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )
    op.create_index("ix_payments_order_id", "payments", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_payments_order_id", table_name="payments")
    op.drop_table("payments")
    op.drop_index("ix_order_status_history_order_id", table_name="order_status_history")
    op.drop_table("order_status_history")
    op.drop_index("ix_order_items_product", table_name="order_items")
    op.drop_index("ix_order_items_order_id", table_name="order_items")
    op.drop_table("order_items")
    op.drop_index("ix_orders_company_id_customer_id", table_name="orders")
    op.drop_index("ix_orders_company_id_status", table_name="orders")
    op.drop_table("orders")
