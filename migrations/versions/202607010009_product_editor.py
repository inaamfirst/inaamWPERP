"""woocommerce style product editor

Revision ID: 202607010009
Revises: 202607010008
Create Date: 2026-07-08 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "202607010009"
down_revision = "202607010008"
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
    op.add_column(
        "product_variants",
        sa.Column("metadata", JSON, nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column("product_images", sa.Column("external_id", MEDIUM))
    op.add_column("product_images", sa.Column("name", LONG))

    op.create_table(
        "product_category_links",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("product_id", UUID, sa.ForeignKey("products.id"), nullable=False),
        sa.Column("category_id", UUID, sa.ForeignKey("categories.id"), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        *timestamps(),
        sa.UniqueConstraint("company_id", "product_id", "category_id"),
    )
    op.create_index(
        "ix_product_category_links_product_id",
        "product_category_links",
        ["product_id"],
    )
    op.create_index(
        "ix_product_category_links_category_id",
        "product_category_links",
        ["category_id"],
    )

    op.create_table(
        "product_tags",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("name", MEDIUM, nullable=False),
        sa.Column("slug", MEDIUM, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *timestamps(),
        sa.UniqueConstraint("company_id", "slug"),
    )
    op.create_index("ix_product_tags_company_id", "product_tags", ["company_id"])

    op.create_table(
        "product_tag_links",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("product_id", UUID, sa.ForeignKey("products.id"), nullable=False),
        sa.Column("tag_id", UUID, sa.ForeignKey("product_tags.id"), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("company_id", "product_id", "tag_id"),
    )
    op.create_index("ix_product_tag_links_product_id", "product_tag_links", ["product_id"])
    op.create_index("ix_product_tag_links_tag_id", "product_tag_links", ["tag_id"])

    op.create_table(
        "product_relationships",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("source_product_id", UUID, sa.ForeignKey("products.id"), nullable=False),
        sa.Column("target_product_id", UUID, sa.ForeignKey("products.id"), nullable=False),
        sa.Column("relationship_type", SHORT, nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        *timestamps(),
        sa.UniqueConstraint(
            "company_id",
            "source_product_id",
            "target_product_id",
            "relationship_type",
        ),
    )
    op.create_index(
        "ix_product_relationships_source_product_id",
        "product_relationships",
        ["source_product_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_product_relationships_source_product_id", table_name="product_relationships")
    op.drop_table("product_relationships")
    op.drop_index("ix_product_tag_links_tag_id", table_name="product_tag_links")
    op.drop_index("ix_product_tag_links_product_id", table_name="product_tag_links")
    op.drop_table("product_tag_links")
    op.drop_index("ix_product_tags_company_id", table_name="product_tags")
    op.drop_table("product_tags")
    op.drop_index("ix_product_category_links_category_id", table_name="product_category_links")
    op.drop_index("ix_product_category_links_product_id", table_name="product_category_links")
    op.drop_table("product_category_links")
    op.drop_column("product_images", "name")
    op.drop_column("product_images", "external_id")
    op.drop_column("product_variants", "metadata")
