"""Add COD, rider finance, and controlled vendor approval workflow.

Revision ID: 202608310024
Revises: 202608210023
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision = "202608310024"
down_revision = "202608210023"
branch_labels = None
depends_on = None

UUID = sa.String(length=36)
NOW = sa.text("CURRENT_TIMESTAMP")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    ]


def upgrade() -> None:
    op.add_column(
        "vendor_order_items",
        sa.Column("finance_status", sa.String(length=40), nullable=False, server_default="pending"),
    )
    op.add_column("vendor_order_items", sa.Column("finance_approved_by_id", UUID))
    op.add_column(
        "vendor_order_items", sa.Column("finance_approved_at", sa.DateTime(timezone=True))
    )
    op.add_column("vendor_order_items", sa.Column("finance_reason", sa.Text()))
    op.create_index(
        "ix_vendor_order_items_company_finance",
        "vendor_order_items",
        ["company_id", "finance_status"],
    )

    op.create_table(
        "rider_finance_profiles",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("rider_user_id", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("delivery_fee_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="PKR"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("metadata", sa.JSON(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("company_id", "rider_user_id", name="uq_rider_finance_profiles_scope"),
    )

    op.create_table(
        "cod_collections",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column(
            "delivery_assignment_id", UUID, sa.ForeignKey("delivery_assignments.id"), nullable=False
        ),
        sa.Column("order_id", UUID, sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("rider_user_id", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("expected_minor", sa.Integer(), nullable=False),
        sa.Column("collected_minor", sa.Integer(), nullable=False),
        sa.Column("accepted_minor", sa.Integer()),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="PKR"),
        sa.Column("receipt_reference", sa.String(length=160), nullable=False),
        sa.Column("proof_reference", sa.String(length=1000), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="submitted"),
        sa.Column("payment_id", UUID, sa.ForeignKey("payments.id")),
        sa.Column("reconciled_by_id", UUID, sa.ForeignKey("users.id")),
        sa.Column("reconciled_at", sa.DateTime(timezone=True)),
        sa.Column("reconciliation_reason", sa.Text()),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("company_id", "idempotency_key", name="uq_cod_collections_idempotency"),
        sa.UniqueConstraint(
            "company_id", "delivery_assignment_id", name="uq_cod_collections_assignment"
        ),
    )
    op.create_index(
        "ix_cod_collections_company_rider_status",
        "cod_collections",
        ["company_id", "rider_user_id", "status"],
    )

    op.create_table(
        "rider_cash_remittances",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("rider_user_id", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="PKR"),
        sa.Column("reference", sa.String(length=160), nullable=False),
        sa.Column("proof_reference", sa.String(length=1000), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="submitted"),
        sa.Column("reconciled_by_id", UUID, sa.ForeignKey("users.id")),
        sa.Column("reconciled_at", sa.DateTime(timezone=True)),
        sa.Column("reconciliation_reason", sa.Text()),
        sa.Column("journal_id", UUID, sa.ForeignKey("ledger_journals.id")),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "company_id", "idempotency_key", name="uq_rider_cash_remittances_idempotency"
        ),
    )
    op.create_index(
        "ix_rider_remittances_company_rider_status",
        "rider_cash_remittances",
        ["company_id", "rider_user_id", "status"],
    )

    op.create_table(
        "rider_ledger_entries",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("rider_user_id", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("entry_type", sa.String(length=40), nullable=False),
        sa.Column("source_type", sa.String(length=80), nullable=False),
        sa.Column("source_id", sa.String(length=120), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("balance_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="PKR"),
        sa.Column("memo", sa.Text()),
        sa.Column("journal_id", UUID, sa.ForeignKey("ledger_journals.id")),
        sa.Column("metadata", sa.JSON(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "company_id",
            "rider_user_id",
            "source_type",
            "source_id",
            name="uq_rider_ledger_entries_source",
        ),
    )
    op.create_index(
        "ix_rider_ledger_entries_company_rider",
        "rider_ledger_entries",
        ["company_id", "rider_user_id", "created_at"],
    )

    op.create_table(
        "rider_payouts",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("rider_user_id", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("payout_number", sa.String(length=80), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="PKR"),
        sa.Column("payment_reference", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="paid"),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_by_id", UUID, sa.ForeignKey("users.id")),
        sa.Column("journal_id", UUID, sa.ForeignKey("ledger_journals.id")),
        sa.Column("metadata", sa.JSON(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "company_id", "rider_user_id", "payout_number", name="uq_rider_payouts_number"
        ),
        sa.UniqueConstraint("company_id", "idempotency_key", name="uq_rider_payouts_idempotency"),
    )

    bind = op.get_bind()
    metadata = sa.MetaData()
    roles = sa.Table("roles", metadata, autoload_with=bind)
    permissions = sa.Table("permissions", metadata, autoload_with=bind)
    role_permissions = sa.Table("role_permissions", metadata, autoload_with=bind)
    for key in ("rider.finance.view", "rider.finance.submit"):
        permission_id = bind.execute(
            sa.select(permissions.c.id).where(permissions.c.key == key)
        ).scalar_one_or_none()
        if permission_id is None:
            permission_id = str(uuid.uuid4())
            bind.execute(
                permissions.insert().values(
                    id=permission_id, key=key, description=f"Permission: {key}"
                )
            )
        rider_role_ids = list(
            bind.execute(sa.select(roles.c.id).where(roles.c.name == "Rider")).scalars()
        )
        for role_id in rider_role_ids:
            present = bind.execute(
                sa.select(role_permissions.c.role_id).where(
                    role_permissions.c.role_id == role_id,
                    role_permissions.c.permission_id == permission_id,
                )
            ).scalar_one_or_none()
            if present is None:
                bind.execute(
                    role_permissions.insert().values(role_id=role_id, permission_id=permission_id)
                )


def downgrade() -> None:
    op.drop_table("rider_payouts")
    op.drop_index("ix_rider_ledger_entries_company_rider", table_name="rider_ledger_entries")
    op.drop_table("rider_ledger_entries")
    op.drop_index("ix_rider_remittances_company_rider_status", table_name="rider_cash_remittances")
    op.drop_table("rider_cash_remittances")
    op.drop_index("ix_cod_collections_company_rider_status", table_name="cod_collections")
    op.drop_table("cod_collections")
    op.drop_table("rider_finance_profiles")
    op.drop_index("ix_vendor_order_items_company_finance", table_name="vendor_order_items")
    with op.batch_alter_table("vendor_order_items") as batch:
        batch.drop_column("finance_reason")
        batch.drop_column("finance_approved_at")
        batch.drop_column("finance_approved_by_id")
        batch.drop_column("finance_status")
