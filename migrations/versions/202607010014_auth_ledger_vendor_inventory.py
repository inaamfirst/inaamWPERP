"""authentication and vendor access foundation

Revision ID: 202607010014
Revises: 202607010013
Create Date: 2026-07-28 00:00:00

This revision is intentionally limited to authentication lifecycle storage and
safe Vendor-role backfill. It must not create or modify accounting, settlement,
vendor-ledger, stock, authoritative-ledger, or vendor-inventory data.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision = "202607010014"
down_revision = "202607010013"
branch_labels = None
depends_on = None

UUID = sa.String(length=36)
SHORT = sa.String(length=40)
LONG = sa.String(length=255)
JSON = sa.JSON()
NOW = sa.text("CURRENT_TIMESTAMP")

VENDOR_SELF_PERMISSIONS = (
    "vendor.orders.view",
    "vendor.products.view",
    "vendor.profile.view",
    "vendor.settlements.view",
)


def _reflected_tables() -> tuple[sa.Table, sa.Table, sa.Table]:
    bind = op.get_bind()
    metadata = sa.MetaData()
    return (
        sa.Table("vendor_users", metadata, autoload_with=bind),
        sa.Table("users", metadata, autoload_with=bind),
        sa.Table("vendors", metadata, autoload_with=bind),
    )


def _vendor_relationship_preflight() -> None:
    """Fail before DDL when a vendor user's tenant or primary link is ambiguous."""

    bind = op.get_bind()
    vendor_users, users, vendors = _reflected_tables()

    tenant_mismatches = (
        bind.execute(
            sa.select(vendor_users.c.user_id)
            .join(users, users.c.id == vendor_users.c.user_id)
            .join(vendors, vendors.c.id == vendor_users.c.vendor_id)
            .where(
                sa.or_(
                    users.c.company_id.is_(None),
                    vendor_users.c.company_id != users.c.company_id,
                    vendor_users.c.company_id != vendors.c.company_id,
                )
            )
            .limit(11)
        )
        .scalars()
        .all()
    )
    if tenant_mismatches:
        sample = ", ".join(str(value) for value in tenant_mismatches[:10])
        raise RuntimeError(
            "Migration 202607010014 refused: VendorUser tenant relationships "
            f"do not match their User/Vendor company (user IDs: {sample})."
        )

    link_count = sa.func.count(vendor_users.c.id)
    primary_count = sa.func.sum(sa.case((vendor_users.c.is_primary.is_(True), 1), else_=0))
    ambiguous_users = (
        bind.execute(
            sa.select(
                vendor_users.c.user_id,
                link_count.label("link_count"),
                primary_count.label("primary_count"),
            )
            .group_by(vendor_users.c.user_id)
            .having(
                sa.or_(
                    primary_count > 1,
                    sa.and_(link_count > 1, primary_count == 0),
                )
            )
            .limit(11)
        )
        .mappings()
        .all()
    )
    if ambiguous_users:
        sample = ", ".join(
            f"{row['user_id']} ({row['link_count']} links, {row['primary_count']} primary)"
            for row in ambiguous_users[:10]
        )
        raise RuntimeError(
            "Migration 202607010014 refused: ambiguous VendorUser primary "
            f"relationships must be resolved first: {sample}."
        )


def _permission_rows(bind: sa.Connection) -> dict[str, str]:
    metadata = sa.MetaData()
    permissions = sa.Table("permissions", metadata, autoload_with=bind)
    existing = {
        row.key: row.id
        for row in bind.execute(
            sa.select(permissions.c.id, permissions.c.key).where(
                permissions.c.key.in_(VENDOR_SELF_PERMISSIONS)
            )
        )
    }
    for key in VENDOR_SELF_PERMISSIONS:
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


def _backfill_vendor_roles() -> None:
    """Add only the minimum self-service role grants for explicit vendor links."""

    bind = op.get_bind()
    metadata = sa.MetaData()
    vendor_users = sa.Table("vendor_users", metadata, autoload_with=bind)
    roles = sa.Table("roles", metadata, autoload_with=bind)
    role_permissions = sa.Table("role_permissions", metadata, autoload_with=bind)
    user_roles = sa.Table("user_roles", metadata, autoload_with=bind)

    # A single relationship is safe to make primary. Multi-link users reached
    # this point only when exactly one primary relationship already exists.
    single_unmarked_users = (
        bind.execute(
            sa.select(vendor_users.c.user_id)
            .group_by(vendor_users.c.user_id)
            .having(
                sa.and_(
                    sa.func.count(vendor_users.c.id) == 1,
                    sa.func.sum(sa.case((vendor_users.c.is_primary.is_(True), 1), else_=0)) == 0,
                )
            )
        )
        .scalars()
        .all()
    )
    if single_unmarked_users:
        bind.execute(
            vendor_users.update()
            .where(vendor_users.c.user_id.in_(single_unmarked_users))
            .values(is_primary=True)
        )

    explicit_vendor_links = bind.execute(
        sa.select(vendor_users.c.company_id, vendor_users.c.user_id)
        .where(sa.func.lower(sa.func.trim(vendor_users.c.role_name)) == "vendor")
        .distinct()
    ).all()
    if not explicit_vendor_links:
        return

    permission_ids = _permission_rows(bind)
    links_by_company: dict[str, set[str]] = {}
    for company_id, user_id in explicit_vendor_links:
        links_by_company.setdefault(company_id, set()).add(user_id)

    for company_id, user_ids in links_by_company.items():
        role_id = bind.execute(
            sa.select(roles.c.id).where(
                roles.c.company_id == company_id,
                roles.c.name == "Vendor",
            )
        ).scalar_one_or_none()
        if role_id is None:
            role_id = str(uuid.uuid4())
            bind.execute(
                roles.insert().values(
                    id=role_id,
                    company_id=company_id,
                    name="Vendor",
                    description=("Vendor portal user restricted to the linked vendor record."),
                )
            )

        existing_permission_ids = set(
            bind.execute(
                sa.select(role_permissions.c.permission_id).where(
                    role_permissions.c.role_id == role_id
                )
            ).scalars()
        )
        for permission_id in permission_ids.values():
            if permission_id not in existing_permission_ids:
                bind.execute(
                    role_permissions.insert().values(
                        role_id=role_id,
                        permission_id=permission_id,
                    )
                )

        existing_user_ids = set(
            bind.execute(
                sa.select(user_roles.c.user_id).where(
                    user_roles.c.role_id == role_id,
                    user_roles.c.user_id.in_(user_ids),
                )
            ).scalars()
        )
        missing_user_ids = user_ids - existing_user_ids
        if missing_user_ids:
            bind.execute(
                user_roles.insert(),
                [{"user_id": user_id, "role_id": role_id} for user_id in sorted(missing_user_ids)],
            )


def upgrade() -> None:
    _vendor_relationship_preflight()

    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column(
                "account_status",
                SHORT,
                nullable=False,
                server_default=sa.text("'active'"),
            )
        )
        batch.add_column(
            sa.Column(
                "must_change_password",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(sa.Column("password_changed_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("last_login_at", sa.DateTime(timezone=True)))

    bind = op.get_bind()
    bind.execute(sa.text("UPDATE users SET account_status = 'stopped' WHERE is_active = false"))

    op.create_table(
        "auth_refresh_tokens",
        sa.Column("id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("session_id", UUID, nullable=False),
        sa.Column("family_id", UUID, nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("replaced_by_id", UUID),
        sa.Column("remember_me", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("user_agent", LONG),
        sa.Column("ip_address", sa.String(length=64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id", name="pk_auth_refresh_tokens"),
        sa.UniqueConstraint("token_hash", name="uq_auth_refresh_tokens_token_hash"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_auth_refresh_tokens_user_id_users"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["auth_sessions.id"],
            name="fk_auth_refresh_tokens_session_id_auth_sessions",
        ),
        sa.ForeignKeyConstraint(
            ["replaced_by_id"],
            ["auth_refresh_tokens.id"],
            name="fk_auth_refresh_tokens_replaced_by_id_auth_refresh_tokens",
        ),
    )
    op.create_index(
        "ix_auth_refresh_tokens_family_id",
        "auth_refresh_tokens",
        ["family_id"],
    )
    op.create_index(
        "ix_auth_refresh_tokens_user_id",
        "auth_refresh_tokens",
        ["user_id"],
    )

    op.create_table(
        "auth_action_tokens",
        sa.Column("id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("purpose", SHORT, nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("metadata", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.PrimaryKeyConstraint("id", name="pk_auth_action_tokens"),
        sa.UniqueConstraint("token_hash", name="uq_auth_action_tokens_token_hash"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_auth_action_tokens_user_id_users"
        ),
    )
    op.create_index(
        "ix_auth_action_tokens_user_id_purpose",
        "auth_action_tokens",
        ["user_id", "purpose"],
    )

    op.create_table(
        "login_throttles",
        sa.Column("id", UUID, nullable=False),
        sa.Column("scope_key", sa.String(length=128), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("blocked_until", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_login_throttles"),
        sa.UniqueConstraint("scope_key", name="uq_login_throttles_scope_key"),
    )

    _backfill_vendor_roles()


def downgrade() -> None:
    # Vendor-role and permission rows are intentionally retained. They may have
    # existed before this revision, and deleting shared RBAC data on downgrade
    # would be less safe than leaving the inert additive grants in place.
    op.drop_table("login_throttles")
    op.drop_index(
        "ix_auth_action_tokens_user_id_purpose",
        table_name="auth_action_tokens",
    )
    op.drop_table("auth_action_tokens")
    op.drop_index(
        "ix_auth_refresh_tokens_user_id",
        table_name="auth_refresh_tokens",
    )
    op.drop_index(
        "ix_auth_refresh_tokens_family_id",
        table_name="auth_refresh_tokens",
    )
    op.drop_table("auth_refresh_tokens")

    with op.batch_alter_table("users") as batch:
        batch.drop_column("last_login_at")
        batch.drop_column("password_changed_at")
        batch.drop_column("must_change_password")
        batch.drop_column("account_status")
