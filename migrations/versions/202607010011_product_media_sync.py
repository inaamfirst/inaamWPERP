"""add product media sync state

Revision ID: 202607010011
Revises: 202607010010
Create Date: 2026-07-11 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "202607010011"
down_revision = "202607010010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("product_images") as batch_op:
        batch_op.add_column(
            sa.Column(
                "sync_status",
                sa.String(length=40),
                nullable=False,
                server_default="pending_add",
            )
        )
        batch_op.add_column(
            sa.Column("last_synced_at", sa.DateTime(timezone=True))
        )
        batch_op.create_unique_constraint(
            "uq_product_images_company_product_external",
            ["company_id", "product_id", "external_id"],
        )

    bind = op.get_bind()
    product_images = sa.table(
        "product_images",
        sa.column("id", sa.String(length=36)),
        sa.column("external_id", sa.String(length=120)),
        sa.column("sync_status", sa.String(length=40)),
        sa.column("last_synced_at", sa.DateTime(timezone=True)),
    )
    sync_outbox = sa.table(
        "sync_outbox",
        sa.column("id", sa.String(length=36)),
        sa.column("connector", sa.String(length=80)),
        sa.column("operation", sa.String(length=80)),
        sa.column("resource_type", sa.String(length=120)),
        sa.column("payload", sa.JSON()),
    )

    bind.execute(
        product_images.update()
        .where(product_images.c.external_id.is_not(None))
        .values(sync_status="synced", last_synced_at=sa.func.now())
    )
    bind.execute(
        product_images.update()
        .where(product_images.c.external_id.is_(None))
        .values(sync_status="pending_add")
    )

    rows = bind.execute(
        sa.select(
            sync_outbox.c.id,
            sync_outbox.c.payload,
        ).where(
            sync_outbox.c.connector == "woocommerce",
            sync_outbox.c.operation == "push",
            sync_outbox.c.resource_type == "product",
        )
    ).all()
    for row in rows:
        payload = row.payload if isinstance(row.payload, dict) else {}
        if "images" not in payload and "_erp_image_sync_state" not in payload:
            continue
        next_payload = dict(payload)
        next_payload.pop("images", None)
        next_payload.pop("_erp_image_sync_state", None)
        bind.execute(
            sync_outbox.update()
            .where(sync_outbox.c.id == row.id)
            .values(payload=next_payload)
        )


def downgrade() -> None:
    with op.batch_alter_table("product_images") as batch_op:
        batch_op.drop_constraint(
            "uq_product_images_company_product_external",
            type_="unique",
        )
        batch_op.drop_column("last_synced_at")
        batch_op.drop_column("sync_status")
