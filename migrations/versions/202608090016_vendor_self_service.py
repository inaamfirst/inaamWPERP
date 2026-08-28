"""Vendor self-service permissions and order-item fulfilment history."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision = "202608090016"
down_revision = "62d9d53e1126"
branch_labels = None
depends_on = None

VENDOR_PERMISSIONS = (
    "vendor.products.manage",
    "vendor.orders.manage",
    "vendor.stock.view",
    "vendor.stock.manage",
    "vendor.reports.view",
)


def upgrade() -> None:
    bind = op.get_bind()
    permissions = sa.table(
        "permissions",
        sa.column("id", sa.String),
        sa.column("key", sa.String),
        sa.column("description", sa.String),
    )
    roles = sa.table(
        "roles",
        sa.column("id", sa.String),
        sa.column("company_id", sa.String),
        sa.column("name", sa.String),
    )
    role_permissions = sa.table(
        "role_permissions", sa.column("role_id", sa.String), sa.column("permission_id", sa.String)
    )
    for key in VENDOR_PERMISSIONS:
        if (
            bind.execute(sa.select(permissions.c.id).where(permissions.c.key == key)).scalar()
            is None
        ):
            bind.execute(
                sa.insert(permissions).values(
                    id=str(uuid.uuid4()), key=key, description=f"Permission: {key}"
                )
            )
    vendor_roles = (
        bind.execute(sa.select(roles.c.id).where(roles.c.name == "Vendor")).scalars().all()
    )
    permission_ids = (
        bind.execute(sa.select(permissions.c.id).where(permissions.c.key.in_(VENDOR_PERMISSIONS)))
        .scalars()
        .all()
    )
    for role_id in vendor_roles:
        for permission_id in permission_ids:
            exists = bind.execute(
                sa.select(role_permissions.c.role_id).where(
                    role_permissions.c.role_id == role_id,
                    role_permissions.c.permission_id == permission_id,
                )
            ).scalar()
            if exists is None:
                bind.execute(
                    sa.insert(role_permissions).values(role_id=role_id, permission_id=permission_id)
                )

    op.create_table(
        "vendor_order_item_status_history",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id", sa.String(length=36), sa.ForeignKey("companies.id"), nullable=False
        ),
        sa.Column(
            "vendor_order_item_id",
            sa.String(length=36),
            sa.ForeignKey("vendor_order_items.id"),
            nullable=False,
        ),
        sa.Column("vendor_id", sa.String(length=36), sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("from_status", sa.String(length=40)),
        sa.Column("to_status", sa.String(length=40), nullable=False),
        sa.Column("changed_by_id", sa.String(length=36), sa.ForeignKey("users.id")),
        sa.Column("reason", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
    )
    op.create_index(
        "ix_vendor_order_item_status_history_scope",
        "vendor_order_item_status_history",
        ["company_id", "vendor_id", "vendor_order_item_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_vendor_order_item_status_history_scope", table_name="vendor_order_item_status_history"
    )
    op.drop_table("vendor_order_item_status_history")
