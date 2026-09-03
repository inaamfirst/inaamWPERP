"""Add WordPress synchronization state to product videos.

Revision ID: 202609030026
Revises: 202609020025
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "202609030026"
down_revision = "202609020025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("product_videos", sa.Column("external_id", sa.String(length=120)))
    op.add_column("product_videos", sa.Column("remote_url", sa.Text()))
    op.add_column(
        "product_videos",
        sa.Column(
            "sync_status",
            sa.String(length=40),
            nullable=False,
            server_default="pending_add",
        ),
    )
    op.add_column(
        "product_videos",
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_column("product_videos", "last_synced_at")
    op.drop_column("product_videos", "sync_status")
    op.drop_column("product_videos", "remote_url")
    op.drop_column("product_videos", "external_id")
