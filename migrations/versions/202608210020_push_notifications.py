"""Add browser push notification subscriptions and outbox."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "202608210020"
down_revision = "202608200019"
branch_labels = None
depends_on = None

UUID = sa.String(length=36)
NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "push_subscriptions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh", sa.Text(), nullable=False),
        sa.Column("auth", sa.Text(), nullable=False),
        sa.Column("expiration_at", sa.DateTime(timezone=True)),
        sa.Column("user_agent", sa.String(length=500)),
        sa.Column("device_label", sa.String(length=120)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.UniqueConstraint("user_id", "endpoint"),
    )
    op.create_index(
        "ix_push_subscriptions_company_user_active",
        "push_subscriptions",
        ["company_id", "user_id", "is_active"],
    )

    op.create_table(
        "push_notifications",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("recipient_user_id", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("order_id", UUID, sa.ForeignKey("orders.id")),
        sa.Column("vendor_id", UUID, sa.ForeignKey("vendors.id")),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("body", sa.String(length=500), nullable=False),
        sa.Column("target_route", sa.String(length=255), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="queued"),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False, unique=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("failed_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )
    op.create_index(
        "ix_push_notifications_status_scheduled_at",
        "push_notifications",
        ["status", "scheduled_at"],
    )
    op.create_index(
        "ix_push_notifications_company_recipient_created_at",
        "push_notifications",
        ["company_id", "recipient_user_id", "created_at"],
    )

    op.create_table(
        "push_delivery_logs",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("notification_id", UUID, sa.ForeignKey("push_notifications.id"), nullable=False),
        sa.Column("subscription_id", UUID, sa.ForeignKey("push_subscriptions.id"), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("adapter", sa.String(length=80), nullable=False, server_default="webpush"),
        sa.Column("provider_message_id", sa.String(length=160)),
        sa.Column("error", sa.Text()),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )
    op.create_index(
        "ix_push_delivery_logs_notification_id",
        "push_delivery_logs",
        ["notification_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_push_delivery_logs_notification_id", table_name="push_delivery_logs")
    op.drop_table("push_delivery_logs")
    op.drop_index(
        "ix_push_notifications_company_recipient_created_at",
        table_name="push_notifications",
    )
    op.drop_index("ix_push_notifications_status_scheduled_at", table_name="push_notifications")
    op.drop_table("push_notifications")
    op.drop_index(
        "ix_push_subscriptions_company_user_active",
        table_name="push_subscriptions",
    )
    op.drop_table("push_subscriptions")
