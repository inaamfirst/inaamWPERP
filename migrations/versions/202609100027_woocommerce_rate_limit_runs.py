"""Add durable WooCommerce run deferral state.

Revision ID: 202609100027
Revises: 202609030026
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "202609100027"
down_revision = "202609030026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sync_run_logs",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_sync_run_logs_connector_status_next_attempt",
        "sync_run_logs",
        ["connector", "status", "next_attempt_at"],
        unique=False,
    )
    # Older releases allowed an active key per vendor. Collapse any in-flight
    # vendor keys into one company key before the upgraded worker resumes.
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, company_id FROM sync_run_logs "
            "WHERE connector = 'woocommerce' AND status IN ('queued', 'running') "
            "ORDER BY started_at DESC, id DESC"
        )
    ).mappings().all()
    bind.execute(
        sa.text(
            "UPDATE sync_run_logs SET active_key = NULL "
            "WHERE connector = 'woocommerce' AND status IN ('queued', 'running')"
        )
    )
    seen_companies: set[str] = set()
    for row in rows:
        company_id = row["company_id"]
        if not company_id:
            continue
        if company_id in seen_companies:
            continue
        bind.execute(
            sa.text("UPDATE sync_run_logs SET active_key = :active_key WHERE id = :id"),
            {"active_key": f"woocommerce:{company_id}", "id": row["id"]},
        )
        seen_companies.add(company_id)


def downgrade() -> None:
    op.drop_index("ix_sync_run_logs_connector_status_next_attempt", table_name="sync_run_logs")
    op.drop_column("sync_run_logs", "next_attempt_at")
