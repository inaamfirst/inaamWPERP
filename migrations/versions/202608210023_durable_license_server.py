"""Add durable license-server state and event history.

Revision ID: 202608210023
Revises: 202608210022
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "202608210023"
down_revision = "202608210022"
branch_labels = None
depends_on = None

UUID = sa.String(length=36)
NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "license_server_records",
        sa.Column("id", UUID, nullable=False),
        sa.Column("license_key_hash", sa.String(length=128), nullable=False),
        sa.Column("company_id", sa.String(length=80), nullable=False),
        sa.Column("company_name", sa.String(length=255), nullable=False),
        sa.Column("device_id", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("plan", sa.String(length=80), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("grace_expires_at", sa.DateTime(timezone=True)),
        sa.Column("signed_payload", sa.Text(), nullable=False),
        sa.Column("signature", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_license_server_records"),
        sa.UniqueConstraint(
            "license_key_hash", name="uq_license_server_records_license_key_hash"
        ),
    )
    op.create_table(
        "license_server_events",
        sa.Column("id", UUID, nullable=False),
        sa.Column("license_id", UUID, nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["license_id"],
            ["license_server_records.id"],
            name="fk_license_server_events_license_id_license_server_records",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_license_server_events"),
    )
    op.create_index(
        "ix_license_server_events_license_created_at",
        "license_server_events",
        ["license_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_license_server_events_license_created_at",
        table_name="license_server_events",
    )
    op.drop_table("license_server_events")
    op.drop_table("license_server_records")
