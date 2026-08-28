"""whatsapp notification foundation

Revision ID: 202607010006
Revises: 202607010005
Create Date: 2026-07-01 00:00:05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "202607010006"
down_revision = "202607010005"
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
        "notification_templates",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("channel", SHORT, nullable=False, server_default="whatsapp"),
        sa.Column("name", MEDIUM, nullable=False),
        sa.Column("language", sa.String(length=12), nullable=False, server_default="en"),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *timestamps(),
        sa.UniqueConstraint("company_id", "channel", "name"),
    )
    op.create_index(
        "ix_notification_templates_company_channel",
        "notification_templates",
        ["company_id", "channel"],
    )

    op.create_table(
        "notification_queue",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("channel", SHORT, nullable=False, server_default="whatsapp"),
        sa.Column("template_id", UUID, sa.ForeignKey("notification_templates.id")),
        sa.Column("recipient_phone", sa.String(length=80), nullable=False),
        sa.Column("message_body", sa.Text(), nullable=False),
        sa.Column("status", SHORT, nullable=False, server_default="queued"),
        sa.Column("idempotency_key", sa.String(length=180), unique=True),
        sa.Column("metadata", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_by_id", UUID, sa.ForeignKey("users.id")),
        sa.Column("scheduled_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("failed_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        *timestamps(),
    )
    op.create_index(
        "ix_notification_queue_company_channel_status",
        "notification_queue",
        ["company_id", "channel", "status"],
    )

    op.create_table(
        "notification_delivery_logs",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("notification_id", UUID, sa.ForeignKey("notification_queue.id"), nullable=False),
        sa.Column("channel", SHORT, nullable=False, server_default="whatsapp"),
        sa.Column("status", SHORT, nullable=False),
        sa.Column("adapter", sa.String(length=80), nullable=False),
        sa.Column("provider_message_id", sa.String(length=160)),
        sa.Column("error", sa.Text()),
        sa.Column("payload", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )
    op.create_index(
        "ix_notification_delivery_logs_notification_id",
        "notification_delivery_logs",
        ["notification_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notification_delivery_logs_notification_id",
        table_name="notification_delivery_logs",
    )
    op.drop_table("notification_delivery_logs")
    op.drop_index(
        "ix_notification_queue_company_channel_status",
        table_name="notification_queue",
    )
    op.drop_table("notification_queue")
    op.drop_index(
        "ix_notification_templates_company_channel",
        table_name="notification_templates",
    )
    op.drop_table("notification_templates")
