from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "202607010015"
down_revision = "202607010014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the vendor product ownership field used by marketplace/sync code."""

    with op.batch_alter_table("vendor_products") as batch:
        batch.add_column(
            sa.Column(
                "ownership_type",
                sa.String(length=40),
                nullable=False,
                server_default="company_owned",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("vendor_products") as batch:
        batch.drop_column("ownership_type")
