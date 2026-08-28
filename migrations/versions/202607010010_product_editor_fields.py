"""persist woocommerce product editor fields

Revision ID: 202607010010
Revises: 202607010009
Create Date: 2026-07-09 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "202607010010"
down_revision = "202607010009"
branch_labels = None
depends_on = None

SHORT = sa.String(length=40)
BACKORDER = sa.String(length=20)
MEDIUM = sa.String(length=120)
LONG = sa.String(length=255)
JSON = sa.JSON()


def upgrade() -> None:
    op.add_column("products", sa.Column("short_description", sa.Text()))
    op.add_column(
        "products",
        sa.Column("visibility", SHORT, nullable=False, server_default="visible"),
    )
    op.add_column(
        "products",
        sa.Column("featured", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("products", sa.Column("global_unique_id", MEDIUM))
    op.add_column(
        "products",
        sa.Column("regular_price_minor", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("products", sa.Column("sale_price_minor", sa.Integer()))
    op.add_column("products", sa.Column("sale_start_at", sa.DateTime(timezone=True)))
    op.add_column("products", sa.Column("sale_end_at", sa.DateTime(timezone=True)))
    op.add_column(
        "products",
        sa.Column("tax_status", SHORT, nullable=False, server_default="taxable"),
    )
    op.add_column("products", sa.Column("tax_class", MEDIUM))
    op.add_column(
        "products",
        sa.Column("manage_stock", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("products", sa.Column("stock_quantity", sa.Integer()))
    op.add_column(
        "products",
        sa.Column("stock_status", SHORT, nullable=False, server_default="instock"),
    )
    op.add_column(
        "products",
        sa.Column("backorders", BACKORDER, nullable=False, server_default="no"),
    )
    op.add_column(
        "products",
        sa.Column("sold_individually", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("products", sa.Column("weight", SHORT))
    op.add_column("products", sa.Column("length", SHORT))
    op.add_column("products", sa.Column("width", SHORT))
    op.add_column("products", sa.Column("height", SHORT))
    op.add_column("products", sa.Column("shipping_class", MEDIUM))
    op.add_column(
        "products",
        sa.Column("reviews_allowed", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("products", sa.Column("purchase_note", sa.Text()))
    op.add_column(
        "products",
        sa.Column("menu_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "products",
        sa.Column("attributes", JSON, nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column(
        "products",
        sa.Column("default_attributes", JSON, nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column(
        "products",
        sa.Column("custom_metadata", JSON, nullable=False, server_default=sa.text("'{}'")),
    )

    op.add_column("product_variants", sa.Column("sale_price_minor", sa.Integer()))
    op.add_column("product_variants", sa.Column("manage_stock", sa.Boolean()))
    op.add_column("product_variants", sa.Column("stock_quantity", sa.Integer()))
    op.add_column("product_variants", sa.Column("stock_status", SHORT))
    op.add_column("product_variants", sa.Column("backorders", BACKORDER))
    op.add_column("product_variants", sa.Column("weight", SHORT))
    op.add_column("product_variants", sa.Column("length", SHORT))
    op.add_column("product_variants", sa.Column("width", SHORT))
    op.add_column("product_variants", sa.Column("height", SHORT))
    op.add_column("product_variants", sa.Column("shipping_class", MEDIUM))
    op.add_column("product_variants", sa.Column("description", sa.Text()))
    op.add_column("product_variants", sa.Column("image_url", sa.Text()))


def downgrade() -> None:
    for column in (
        "image_url",
        "description",
        "shipping_class",
        "height",
        "width",
        "length",
        "weight",
        "backorders",
        "stock_status",
        "stock_quantity",
        "manage_stock",
        "sale_price_minor",
    ):
        op.drop_column("product_variants", column)

    for column in (
        "custom_metadata",
        "default_attributes",
        "attributes",
        "menu_order",
        "purchase_note",
        "reviews_allowed",
        "shipping_class",
        "height",
        "width",
        "length",
        "weight",
        "sold_individually",
        "backorders",
        "stock_status",
        "stock_quantity",
        "manage_stock",
        "tax_class",
        "tax_status",
        "sale_end_at",
        "sale_start_at",
        "sale_price_minor",
        "regular_price_minor",
        "global_unique_id",
        "featured",
        "visibility",
        "short_description",
    ):
        op.drop_column("products", column)
