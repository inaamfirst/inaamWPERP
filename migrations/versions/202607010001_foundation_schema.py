"""foundation schema

Revision ID: 202607010001
Revises:
Create Date: 2026-07-01 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "202607010001"
down_revision = None
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
        "companies",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("name", LONG, nullable=False),
        sa.Column("legal_name", LONG),
        sa.Column("status", SHORT, nullable=False, server_default="active"),
        *timestamps(),
    )

    op.create_table(
        "users",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id")),
        sa.Column("username", MEDIUM, nullable=False),
        sa.Column("email", LONG, unique=True),
        sa.Column("password_hash", LONG, nullable=False),
        sa.Column("full_name", LONG),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *timestamps(),
        sa.UniqueConstraint("company_id", "username"),
    )

    op.create_table(
        "roles",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id")),
        sa.Column("name", MEDIUM, nullable=False),
        sa.Column("description", sa.Text()),
        *timestamps(),
        sa.UniqueConstraint("company_id", "name"),
    )

    op.create_table(
        "permissions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("key", sa.String(length=160), nullable=False, unique=True),
        sa.Column("description", sa.Text()),
        *timestamps(),
    )

    op.create_table(
        "role_permissions",
        sa.Column("role_id", UUID, sa.ForeignKey("roles.id"), primary_key=True),
        sa.Column("permission_id", UUID, sa.ForeignKey("permissions.id"), primary_key=True),
        sa.UniqueConstraint("role_id", "permission_id"),
    )

    op.create_table(
        "user_roles",
        sa.Column("user_id", UUID, sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("role_id", UUID, sa.ForeignKey("roles.id"), primary_key=True),
        sa.UniqueConstraint("user_id", "role_id"),
    )

    op.create_table(
        "settings",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id")),
        sa.Column("key", sa.String(length=160), nullable=False),
        sa.Column("value", JSON, nullable=False),
        *timestamps(),
        sa.UniqueConstraint("company_id", "key"),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id")),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id")),
        sa.Column("action", sa.String(length=160), nullable=False),
        sa.Column("entity_type", sa.String(length=160)),
        sa.Column("entity_id", MEDIUM),
        sa.Column("metadata", JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )

    op.create_table(
        "external_resource_map",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id")),
        sa.Column("connector", sa.String(length=80), nullable=False),
        sa.Column("internal_resource_type", MEDIUM, nullable=False),
        sa.Column("internal_resource_id", MEDIUM, nullable=False),
        sa.Column("external_resource_type", MEDIUM, nullable=False),
        sa.Column("external_resource_id", sa.String(length=160), nullable=False),
        sa.Column("version", MEDIUM),
        sa.Column("metadata", JSON, nullable=False),
        *timestamps(),
        sa.UniqueConstraint(
            "company_id",
            "connector",
            "external_resource_type",
            "external_resource_id",
            name="uq_external_resource_map_external",
        ),
    )

    op.create_table(
        "sync_outbox",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id")),
        sa.Column("connector", sa.String(length=80), nullable=False),
        sa.Column("operation", sa.String(length=80), nullable=False),
        sa.Column("resource_type", MEDIUM, nullable=False),
        sa.Column("resource_id", MEDIUM),
        sa.Column("payload", JSON, nullable=False),
        sa.Column("idempotency_key", sa.String(length=180), nullable=False, unique=True),
        sa.Column("status", SHORT, nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        *timestamps(),
    )

    op.create_table(
        "sync_inbox_logs",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("connector", sa.String(length=80), nullable=False),
        sa.Column("external_event_id", sa.String(length=180), nullable=False),
        sa.Column("event_type", MEDIUM, nullable=False),
        sa.Column("payload", JSON, nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("status", SHORT, nullable=False, server_default="received"),
        sa.Column("error", sa.Text()),
        sa.UniqueConstraint("connector", "external_event_id"),
    )

    op.create_table(
        "sync_conflicts",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id")),
        sa.Column("connector", sa.String(length=80), nullable=False),
        sa.Column("resource_type", MEDIUM, nullable=False),
        sa.Column("resource_id", MEDIUM),
        sa.Column("external_resource_id", sa.String(length=160)),
        sa.Column("conflict_type", MEDIUM, nullable=False),
        sa.Column("local_payload", JSON, nullable=False),
        sa.Column("remote_payload", JSON, nullable=False),
        sa.Column("status", SHORT, nullable=False, server_default="open"),
        sa.Column("resolution", sa.Text()),
        *timestamps(),
    )

    op.create_table(
        "sync_run_logs",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("connector", sa.String(length=80), nullable=False),
        sa.Column("direction", SHORT, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", SHORT, nullable=False, server_default="running"),
        sa.Column("stats", JSON, nullable=False),
        sa.Column("error", sa.Text()),
    )

    op.create_table(
        "licenses",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id")),
        sa.Column("license_key_hash", LONG),
        sa.Column("status", SHORT, nullable=False, server_default="inactive"),
        sa.Column("plan", sa.String(length=80)),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("metadata", JSON, nullable=False),
        *timestamps(),
    )

    op.create_index(
        "ix_audit_logs_company_id_created_at",
        "audit_logs",
        ["company_id", "created_at"],
    )
    op.create_index(
        "ix_sync_outbox_status_next_attempt_at",
        "sync_outbox",
        ["status", "next_attempt_at"],
    )
    op.create_index("ix_sync_conflicts_status", "sync_conflicts", ["status"])
    op.create_index(
        "ix_sync_run_logs_connector_started_at",
        "sync_run_logs",
        ["connector", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_sync_run_logs_connector_started_at", table_name="sync_run_logs")
    op.drop_index("ix_sync_conflicts_status", table_name="sync_conflicts")
    op.drop_index("ix_sync_outbox_status_next_attempt_at", table_name="sync_outbox")
    op.drop_index("ix_audit_logs_company_id_created_at", table_name="audit_logs")

    op.drop_table("licenses")
    op.drop_table("sync_run_logs")
    op.drop_table("sync_conflicts")
    op.drop_table("sync_inbox_logs")
    op.drop_table("sync_outbox")
    op.drop_table("external_resource_map")
    op.drop_table("audit_logs")
    op.drop_table("settings")
    op.drop_table("user_roles")
    op.drop_table("role_permissions")
    op.drop_table("permissions")
    op.drop_table("roles")
    op.drop_table("users")
    op.drop_table("companies")
