"""Unified shop/online commerce workspace foundations."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "202608120017"
down_revision = "202608090016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "customers",
        sa.Column("source_channel", sa.String(length=40), nullable=False, server_default="legacy"),
    )
    op.add_column(
        "orders",
        sa.Column("sales_channel", sa.String(length=40), nullable=False, server_default="legacy"),
    )
    op.add_column(
        "orders",
        sa.Column("order_source", sa.String(length=40), nullable=False, server_default="legacy"),
    )
    op.add_column("orders", sa.Column("external_order_id", sa.String(length=160), nullable=True))
    op.add_column(
        "orders",
        sa.Column(
            "reservation_status", sa.String(length=40), nullable=False, server_default="none"
        ),
    )
    op.create_index(
        "ix_orders_channel_source", "orders", ["company_id", "sales_channel", "order_source"]
    )

    op.create_table(
        "product_channel_listings",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id", sa.String(length=36), sa.ForeignKey("companies.id"), nullable=False
        ),
        sa.Column("product_id", sa.String(length=36), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("vendor_id", sa.String(length=36), sa.ForeignKey("vendors.id"), nullable=True),
        sa.Column("channel", sa.String(length=40), nullable=False, server_default="woocommerce"),
        sa.Column("listing_status", sa.String(length=40), nullable=False, server_default="private"),
        sa.Column("channel_sku", sa.String(length=120), nullable=True),
        sa.Column("price_minor", sa.Integer(), nullable=True),
        sa.Column("external_id", sa.String(length=160), nullable=True),
        sa.Column("sync_status", sa.String(length=40), nullable=False, server_default="pending"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.UniqueConstraint("company_id", "product_id", "channel"),
    )
    op.create_index(
        "ix_product_channel_listings_scope",
        "product_channel_listings",
        ["company_id", "vendor_id", "channel"],
    )

    op.create_table(
        "stock_reservations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id", sa.String(length=36), sa.ForeignKey("companies.id"), nullable=False
        ),
        sa.Column(
            "warehouse_id", sa.String(length=36), sa.ForeignKey("warehouses.id"), nullable=False
        ),
        sa.Column("product_id", sa.String(length=36), sa.ForeignKey("products.id"), nullable=False),
        sa.Column(
            "variant_id", sa.String(length=36), sa.ForeignKey("product_variants.id"), nullable=True
        ),
        sa.Column("source_type", sa.String(length=80), nullable=False),
        sa.Column("source_id", sa.String(length=120), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="reserved"),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.UniqueConstraint("company_id", "idempotency_key"),
    )
    op.create_index(
        "ix_stock_reservations_available",
        "stock_reservations",
        ["company_id", "warehouse_id", "product_id", "status"],
    )

    op.create_table(
        "support_contacts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id", sa.String(length=36), sa.ForeignKey("companies.id"), nullable=False
        ),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("role", sa.String(length=80), nullable=False, server_default="support"),
        sa.Column("phone", sa.String(length=80), nullable=False),
        sa.Column("whatsapp_message", sa.Text(), nullable=True),
        sa.Column("working_hours", sa.String(length=255), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.UniqueConstraint("company_id", "phone"),
    )


def downgrade() -> None:
    op.drop_table("support_contacts")
    op.drop_index("ix_stock_reservations_available", table_name="stock_reservations")
    op.drop_table("stock_reservations")
    op.drop_index("ix_product_channel_listings_scope", table_name="product_channel_listings")
    op.drop_table("product_channel_listings")
    op.drop_index("ix_orders_channel_source", table_name="orders")
    op.drop_column("orders", "reservation_status")
    op.drop_column("orders", "external_order_id")
    op.drop_column("orders", "order_source")
    op.drop_column("orders", "sales_channel")
    op.drop_column("customers", "source_channel")
