"""catalog and customers

Revision ID: 202607010003
Revises: 202607010002
Create Date: 2026-07-01 00:00:02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "202607010003"
down_revision = "202607010002"
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
        "categories",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("parent_id", UUID, sa.ForeignKey("categories.id")),
        sa.Column("name", LONG, nullable=False),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *timestamps(),
        sa.UniqueConstraint("company_id", "slug", name="uq_categories_company_slug"),
    )
    op.create_index("ix_categories_company_id", "categories", ["company_id"])

    op.create_table(
        "brands",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("name", LONG, nullable=False),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *timestamps(),
        sa.UniqueConstraint("company_id", "slug", name="uq_brands_company_slug"),
    )
    op.create_index("ix_brands_company_id", "brands", ["company_id"])

    op.create_table(
        "products",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("category_id", UUID, sa.ForeignKey("categories.id")),
        sa.Column("brand_id", UUID, sa.ForeignKey("brands.id")),
        sa.Column("name", LONG, nullable=False),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("sku", MEDIUM),
        sa.Column("barcode", MEDIUM),
        sa.Column("product_type", SHORT, nullable=False, server_default="simple"),
        sa.Column("status", SHORT, nullable=False, server_default="active"),
        sa.Column("description", sa.Text()),
        sa.Column("seo_title", LONG),
        sa.Column("seo_description", sa.Text()),
        sa.Column("metadata", JSON, nullable=False, server_default=sa.text("'{}'")),
        *timestamps(),
        sa.UniqueConstraint("company_id", "slug", name="uq_products_company_slug"),
        sa.UniqueConstraint("company_id", "sku", name="uq_products_company_sku"),
    )
    op.create_index("ix_products_company_id_status", "products", ["company_id", "status"])

    op.create_table(
        "product_variants",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("product_id", UUID, sa.ForeignKey("products.id"), nullable=False),
        sa.Column("name", LONG),
        sa.Column("sku", MEDIUM),
        sa.Column("barcode", MEDIUM),
        sa.Column("price_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_minor", sa.Integer()),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="PKR"),
        sa.Column("attributes", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *timestamps(),
        sa.UniqueConstraint("company_id", "sku", name="uq_product_variants_company_sku"),
    )
    op.create_index("ix_product_variants_product_id", "product_variants", ["product_id"])

    op.create_table(
        "product_images",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("product_id", UUID, sa.ForeignKey("products.id"), nullable=False),
        sa.Column("variant_id", UUID, sa.ForeignKey("product_variants.id")),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("alt_text", LONG),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        *timestamps(),
    )
    op.create_index("ix_product_images_product_id", "product_images", ["product_id"])

    op.create_table(
        "customers",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("full_name", LONG, nullable=False),
        sa.Column("email", LONG),
        sa.Column("phone", sa.String(length=80)),
        sa.Column("status", SHORT, nullable=False, server_default="active"),
        sa.Column("credit_limit_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata", JSON, nullable=False, server_default=sa.text("'{}'")),
        *timestamps(),
        sa.UniqueConstraint("company_id", "email", name="uq_customers_company_email"),
        sa.UniqueConstraint("company_id", "phone", name="uq_customers_company_phone"),
    )
    op.create_index("ix_customers_company_id_status", "customers", ["company_id", "status"])

    op.create_table(
        "customer_addresses",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("customer_id", UUID, sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("label", sa.String(length=80)),
        sa.Column("recipient_name", LONG),
        sa.Column("phone", sa.String(length=80)),
        sa.Column("line1", LONG, nullable=False),
        sa.Column("line2", LONG),
        sa.Column("city", MEDIUM),
        sa.Column("state", MEDIUM),
        sa.Column("postal_code", SHORT),
        sa.Column("country", sa.String(length=2), nullable=False, server_default="PK"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        *timestamps(),
    )
    op.create_index("ix_customer_addresses_customer_id", "customer_addresses", ["customer_id"])

    op.create_table(
        "customer_notes",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("customer_id", UUID, sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("created_by_id", UUID, sa.ForeignKey("users.id")),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )
    op.create_index("ix_customer_notes_customer_id", "customer_notes", ["customer_id"])

    op.create_table(
        "customer_tags",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("customer_id", UUID, sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("tag", sa.String(length=80), nullable=False),
        *timestamps(),
        sa.UniqueConstraint(
            "company_id",
            "customer_id",
            "tag",
            name="uq_customer_tags_company_customer_tag",
        ),
    )
    op.create_index("ix_customer_tags_customer_id", "customer_tags", ["customer_id"])


def downgrade() -> None:
    op.drop_index("ix_customer_tags_customer_id", table_name="customer_tags")
    op.drop_table("customer_tags")
    op.drop_index("ix_customer_notes_customer_id", table_name="customer_notes")
    op.drop_table("customer_notes")
    op.drop_index("ix_customer_addresses_customer_id", table_name="customer_addresses")
    op.drop_table("customer_addresses")
    op.drop_index("ix_customers_company_id_status", table_name="customers")
    op.drop_table("customers")
    op.drop_index("ix_product_images_product_id", table_name="product_images")
    op.drop_table("product_images")
    op.drop_index("ix_product_variants_product_id", table_name="product_variants")
    op.drop_table("product_variants")
    op.drop_index("ix_products_company_id_status", table_name="products")
    op.drop_table("products")
    op.drop_index("ix_brands_company_id", table_name="brands")
    op.drop_table("brands")
    op.drop_index("ix_categories_company_id", table_name="categories")
    op.drop_table("categories")
