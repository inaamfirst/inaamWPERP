"""sync run company scope

Revision ID: 202607010007
Revises: 202607010006
Create Date: 2026-07-01 00:00:06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "202607010007"
down_revision = "202607010006"
branch_labels = None
depends_on = None

UUID = sa.String(length=36)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("sync_run_logs") as batch:
            batch.add_column(sa.Column("company_id", UUID, nullable=True))
            batch.create_foreign_key(
                "fk_sync_run_logs_company_id_companies",
                "companies",
                ["company_id"],
                ["id"],
            )
    else:
        op.add_column("sync_run_logs", sa.Column("company_id", UUID, nullable=True))
        op.create_foreign_key(
            "fk_sync_run_logs_company_id_companies",
            "sync_run_logs",
            "companies",
            ["company_id"],
            ["id"],
        )
    op.create_index(
        "ix_sync_run_logs_company_connector_started_at",
        "sync_run_logs",
        ["company_id", "connector", "started_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_sync_run_logs_company_connector_started_at",
        table_name="sync_run_logs",
    )
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("sync_run_logs") as batch:
            batch.drop_constraint(
                "fk_sync_run_logs_company_id_companies",
                type_="foreignkey",
            )
            batch.drop_column("company_id")
    else:
        op.drop_constraint(
            "fk_sync_run_logs_company_id_companies",
            "sync_run_logs",
            type_="foreignkey",
        )
        op.drop_column("sync_run_logs", "company_id")
