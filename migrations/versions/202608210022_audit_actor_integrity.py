"""Repair audit actor references and retain audit history safely.

Revision ID: 202608210022
Revises: 202608210021
"""

from __future__ import annotations

from alembic import op

revision = "202608210022"
down_revision = "202608210021"
branch_labels = None
depends_on = None

FK_NAME = "fk_audit_logs_user_id_users"


def _replace_user_foreign_key(*, ondelete: str | None) -> None:
    with op.batch_alter_table("audit_logs") as batch_op:
        batch_op.drop_constraint(FK_NAME, type_="foreignkey")
        batch_op.create_foreign_key(
            FK_NAME,
            "users",
            ["user_id"],
            ["id"],
            ondelete=ondelete,
        )


def upgrade() -> None:
    # Historical logs remain useful after users are removed.  Null is the
    # schema's explicit representation for a deleted or non-user actor.
    op.execute(
        """
        UPDATE audit_logs
        SET user_id = NULL
        WHERE user_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM users WHERE users.id = audit_logs.user_id
          )
        """
    )
    _replace_user_foreign_key(ondelete="SET NULL")


def downgrade() -> None:
    _replace_user_foreign_key(ondelete=None)
