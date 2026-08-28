"""Add role-scoped delivery assignments and rider permissions."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision = "202608120018"
down_revision = "202608120017"
branch_labels = None
depends_on = None

DELIVERY_PERMISSIONS = (
    "delivery.manage",
    "delivery.view_assigned",
    "delivery.update_assigned",
)


def _permission_ids(bind: sa.Connection) -> dict[str, str]:
    metadata = sa.MetaData()
    permissions = sa.Table("permissions", metadata, autoload_with=bind)
    existing = {
        row.key: row.id
        for row in bind.execute(
            sa.select(permissions.c.id, permissions.c.key).where(
                permissions.c.key.in_(DELIVERY_PERMISSIONS)
            )
        )
    }
    for key in DELIVERY_PERMISSIONS:
        if key in existing:
            continue
        permission_id = str(uuid.uuid4())
        bind.execute(
            permissions.insert().values(
                id=permission_id,
                key=key,
                description=f"Permission: {key}",
            )
        )
        existing[key] = permission_id
    return existing


def _seed_rider_roles() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    companies = sa.Table("companies", metadata, autoload_with=bind)
    roles = sa.Table("roles", metadata, autoload_with=bind)
    role_permissions = sa.Table("role_permissions", metadata, autoload_with=bind)
    permission_ids = _permission_ids(bind)

    for company_id, in bind.execute(sa.select(companies.c.id)):
        rider_role_id = bind.execute(
            sa.select(roles.c.id).where(
                roles.c.company_id == company_id,
                roles.c.name == "Rider",
            )
        ).scalar_one_or_none()
        if rider_role_id is None:
            rider_role_id = str(uuid.uuid4())
            bind.execute(
                roles.insert().values(
                    id=rider_role_id,
                    company_id=company_id,
                    name="Rider",
                    description="Delivery rider restricted to assigned orders.",
                )
            )

        existing_ids = set(
            bind.execute(
                sa.select(role_permissions.c.permission_id).where(
                    role_permissions.c.role_id == rider_role_id
                )
            ).scalars()
        )
        missing = [
            {"role_id": rider_role_id, "permission_id": permission_id}
            for permission_id in permission_ids.values()
            if permission_id not in existing_ids
        ]
        if missing:
            bind.execute(role_permissions.insert(), missing)


def upgrade() -> None:
    op.create_table(
        "delivery_assignments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id", sa.String(length=36), sa.ForeignKey("companies.id"), nullable=False
        ),
        sa.Column("order_id", sa.String(length=36), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column(
            "rider_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="assigned"),
        sa.Column("recipient_name", sa.String(length=255), nullable=False),
        sa.Column("recipient_phone", sa.String(length=80)),
        sa.Column("address_line1", sa.String(length=255), nullable=False),
        sa.Column("address_line2", sa.String(length=255)),
        sa.Column("city", sa.String(length=120)),
        sa.Column("state", sa.String(length=120)),
        sa.Column("postal_code", sa.String(length=40)),
        sa.Column("country", sa.String(length=2), nullable=False, server_default="PK"),
        sa.Column("assigned_by_id", sa.String(length=36), sa.ForeignKey("users.id")),
        sa.Column("picked_up_at", sa.DateTime(timezone=True)),
        sa.Column("out_for_delivery_at", sa.DateTime(timezone=True)),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("failed_at", sa.DateTime(timezone=True)),
        sa.Column("failure_reason", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.UniqueConstraint("company_id", "order_id"),
    )
    op.create_index(
        "ix_delivery_assignments_rider_status",
        "delivery_assignments",
        ["company_id", "rider_user_id", "status"],
    )
    op.create_index(
        "ix_delivery_assignments_company_status",
        "delivery_assignments",
        ["company_id", "status"],
    )
    op.create_table(
        "delivery_status_history",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id", sa.String(length=36), sa.ForeignKey("companies.id"), nullable=False
        ),
        sa.Column(
            "delivery_assignment_id",
            sa.String(length=36),
            sa.ForeignKey("delivery_assignments.id"),
            nullable=False,
        ),
        sa.Column("from_status", sa.String(length=40)),
        sa.Column("to_status", sa.String(length=40), nullable=False),
        sa.Column("changed_by_id", sa.String(length=36), sa.ForeignKey("users.id")),
        sa.Column("reason", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
    )
    op.create_index(
        "ix_delivery_status_history_assignment",
        "delivery_status_history",
        ["company_id", "delivery_assignment_id", "created_at"],
    )
    _seed_rider_roles()


def downgrade() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    roles = sa.Table("roles", metadata, autoload_with=bind)
    role_permissions = sa.Table("role_permissions", metadata, autoload_with=bind)
    permissions = sa.Table("permissions", metadata, autoload_with=bind)
    permission_ids = list(
        bind.execute(
            sa.select(permissions.c.id).where(permissions.c.key.in_(DELIVERY_PERMISSIONS))
        ).scalars()
    )
    if permission_ids:
        bind.execute(
            role_permissions.delete().where(role_permissions.c.permission_id.in_(permission_ids))
        )
        bind.execute(permissions.delete().where(permissions.c.id.in_(permission_ids)))
    bind.execute(roles.delete().where(roles.c.name == "Rider"))
    op.drop_index("ix_delivery_status_history_assignment", table_name="delivery_status_history")
    op.drop_table("delivery_status_history")
    op.drop_index("ix_delivery_assignments_company_status", table_name="delivery_assignments")
    op.drop_index("ix_delivery_assignments_rider_status", table_name="delivery_assignments")
    op.drop_table("delivery_assignments")
