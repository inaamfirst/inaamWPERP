from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "202607010013"
down_revision = "202607010012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Turn sync-run audit rows into durable, lease-backed worker jobs.

    Existing completed audit rows remain unchanged.  A legacy process may have
    left more than one ``running`` row behind; keep the newest as recoverable
    and close older duplicates as historical failures before adding the unique
    active-job key.
    """

    with op.batch_alter_table("sync_run_logs") as batch_op:
        batch_op.add_column(sa.Column("active_key", sa.String(length=200), nullable=True))
        batch_op.add_column(
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("worker_id", sa.String(length=160), nullable=True))
        batch_op.add_column(
            sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0"))
        )

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT id, company_id, connector FROM sync_run_logs "
            "WHERE status IN ('queued', 'running') "
            "ORDER BY company_id, connector, started_at DESC, id DESC"
        )
    ).mappings()
    active_keys: set[str] = set()
    for row in rows:
        company_id = row["company_id"]
        connector = row["connector"]
        if not company_id:
            connection.execute(
                sa.text(
                    "UPDATE sync_run_logs SET status = 'failed', finished_at = CURRENT_TIMESTAMP, "
                    "error = :error WHERE id = :id"
                ),
                {
                    "id": row["id"],
                    "error": (
                        "Recovered during durable sync-job migration: "
                        "company scope was missing."
                    ),
                },
            )
            continue
        active_key = f"{connector}:{company_id}"
        if active_key in active_keys:
            connection.execute(
                sa.text(
                    "UPDATE sync_run_logs SET status = 'failed', finished_at = CURRENT_TIMESTAMP, "
                    "error = :error WHERE id = :id"
                ),
                {
                    "id": row["id"],
                    "error": (
                        "Recovered during durable sync-job migration: "
                        "superseded duplicate active run."
                    ),
                },
            )
            continue
        active_keys.add(active_key)
        connection.execute(
            sa.text("UPDATE sync_run_logs SET active_key = :active_key WHERE id = :id"),
            {"id": row["id"], "active_key": active_key},
        )

    with op.batch_alter_table("sync_run_logs") as batch_op:
        batch_op.create_unique_constraint("uq_sync_run_logs_active_key", ["active_key"])


def downgrade() -> None:
    with op.batch_alter_table("sync_run_logs") as batch_op:
        batch_op.drop_constraint("uq_sync_run_logs_active_key", type_="unique")
        batch_op.drop_column("attempts")
        batch_op.drop_column("worker_id")
        batch_op.drop_column("lease_expires_at")
        batch_op.drop_column("active_key")
