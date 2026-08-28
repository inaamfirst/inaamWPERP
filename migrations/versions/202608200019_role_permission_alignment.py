"""Align canonical Manager and Vendor permissions with the web workspaces."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision = "202608200019"
down_revision = "202608120018"
branch_labels = None
depends_on = None

MANAGER_DESCRIPTION = "Default manager role for operations."
MANAGER_PERMISSIONS = frozenset(
    {
        "catalog.view",
        "catalog.manage",
        "customers.view",
        "customers.manage",
        "inventory.view",
        "inventory.manage",
        "inventory.transfer",
        "orders.view",
        "orders.manage",
        "orders.change_status",
        "delivery.manage",
        "reports.view",
        "reports.export",
    }
)
VENDOR_LEDGER_PERMISSION = "vendor.ledger.view"
VENDOR_DESCRIPTION = "Default vendor role with canonical portal permissions."
LEGACY_VENDOR_DESCRIPTION = "Vendor portal user restricted to the linked vendor record."


def _ensure_permission(bind: sa.Connection, permissions: sa.Table, key: str) -> str:
    permission_id = bind.execute(
        sa.select(permissions.c.id).where(permissions.c.key == key)
    ).scalar_one_or_none()
    if permission_id is not None:
        return str(permission_id)
    permission_id = str(uuid.uuid4())
    bind.execute(
        permissions.insert().values(
            id=permission_id,
            key=key,
            description=f"Permission: {key}",
        )
    )
    return permission_id


def upgrade() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    roles = sa.Table("roles", metadata, autoload_with=bind)
    permissions = sa.Table("permissions", metadata, autoload_with=bind)
    role_permissions = sa.Table("role_permissions", metadata, autoload_with=bind)

    manager_permission_ids = {
        _ensure_permission(bind, permissions, key) for key in MANAGER_PERMISSIONS
    }
    vendor_ledger_id = _ensure_permission(bind, permissions, VENDOR_LEDGER_PERMISSION)

    manager_role_ids = list(
        bind.execute(
            sa.select(roles.c.id).where(
                roles.c.name == "Manager",
                roles.c.description == MANAGER_DESCRIPTION,
            )
        ).scalars()
    )
    for role_id in manager_role_ids:
        bind.execute(role_permissions.delete().where(role_permissions.c.role_id == role_id))
        if manager_permission_ids:
            bind.execute(
                role_permissions.insert(),
                [
                    {"role_id": role_id, "permission_id": permission_id}
                    for permission_id in sorted(manager_permission_ids)
                ],
            )

    vendor_role_ids = list(
        bind.execute(
            sa.select(roles.c.id).where(
                roles.c.name == "Vendor",
                roles.c.description.in_([VENDOR_DESCRIPTION, LEGACY_VENDOR_DESCRIPTION]),
            )
        ).scalars()
    )
    for role_id in vendor_role_ids:
        exists = bind.execute(
            sa.select(role_permissions.c.role_id).where(
                role_permissions.c.role_id == role_id,
                role_permissions.c.permission_id == vendor_ledger_id,
            )
        ).scalar_one_or_none()
        if exists is None:
            bind.execute(
                role_permissions.insert().values(
                    role_id=role_id,
                    permission_id=vendor_ledger_id,
                )
            )


def downgrade() -> None:
    # Permission corrections are intentionally retained. Removing grants on
    # downgrade could unexpectedly lock active accounts out of their workspace.
    return
