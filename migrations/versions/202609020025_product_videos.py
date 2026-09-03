"""Add ERP-only product videos.

Revision ID: 202609020025
Revises: 202608310024
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "202609020025"
down_revision = "202608310024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_videos",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            sa.String(length=36),
            sa.ForeignKey("products.id"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("name", sa.String(length=255)),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_product_videos_product_id", "product_videos", ["product_id"])


def downgrade() -> None:
    op.drop_index("ix_product_videos_product_id", table_name="product_videos")
    op.drop_table("product_videos")
