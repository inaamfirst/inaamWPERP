"""Create authoritative ledger and vendor-inventory runtime tables.

Revision ID: 202608210021
Revises: 202608210020

The superseded e4b6313c83e3 autogeneration combined these required tables
with unrelated destructive schema drift.  Its replacement compatibility
revision, 62d9d53e1126, intentionally performed no work.  This forward
repair is conditional so it also adopts databases where application tests
or an operator created some or all of the tables outside Alembic.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "202608210021"
down_revision = "202608210020"
branch_labels = None
depends_on = None

UUID = sa.String(length=36)
NOW = sa.text("CURRENT_TIMESTAMP")

RUNTIME_TABLES = (
    "ledger_accounts",
    "ledger_periods",
    "ledger_journals",
    "ledger_lines",
    "vendor_inventory_balances",
    "vendor_inventory_movements",
)


def _create_ledger_accounts() -> None:
    op.create_table(
        "ledger_accounts",
        sa.Column("id", UUID, nullable=False),
        sa.Column("company_id", UUID, nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("account_type", sa.String(length=40), nullable=False),
        sa.Column("parent_id", UUID),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("legacy_account_id", UUID),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name="fk_ledger_accounts_company_id_companies"
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["ledger_accounts.id"],
            name="fk_ledger_accounts_parent_id_ledger_accounts",
        ),
        sa.ForeignKeyConstraint(
            ["legacy_account_id"],
            ["accounts.id"],
            name="fk_ledger_accounts_legacy_account_id_accounts",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ledger_accounts"),
        sa.UniqueConstraint(
            "company_id", "code", name="uq_ledger_accounts_company_code"
        ),
    )


def _create_ledger_periods() -> None:
    op.create_table(
        "ledger_periods",
        sa.Column("id", UUID, nullable=False),
        sa.Column("company_id", UUID, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("closed_by_id", UUID),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name="fk_ledger_periods_company_id_companies"
        ),
        sa.ForeignKeyConstraint(
            ["closed_by_id"], ["users.id"], name="fk_ledger_periods_closed_by_id_users"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ledger_periods"),
        sa.UniqueConstraint(
            "company_id", "name", name="uq_ledger_periods_company_name"
        ),
    )


def _create_ledger_journals() -> None:
    op.create_table(
        "ledger_journals",
        sa.Column("id", UUID, nullable=False),
        sa.Column("company_id", UUID, nullable=False),
        sa.Column("entry_number", sa.String(length=80), nullable=False),
        sa.Column("source_type", sa.String(length=80), nullable=False),
        sa.Column("source_id", sa.String(length=120), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_id", UUID),
        sa.Column("reversal_of_id", UUID),
        sa.Column("memo", sa.Text()),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name="fk_ledger_journals_company_id_companies"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], name="fk_ledger_journals_created_by_id_users"
        ),
        sa.ForeignKeyConstraint(
            ["reversal_of_id"],
            ["ledger_journals.id"],
            name="fk_ledger_journals_reversal_of_id_ledger_journals",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ledger_journals"),
        sa.UniqueConstraint(
            "company_id",
            "entry_number",
            name="uq_ledger_journals_company_entry_number",
        ),
        sa.UniqueConstraint(
            "company_id",
            "idempotency_key",
            name="uq_ledger_journals_company_idempotency_key",
        ),
    )


def _create_ledger_lines() -> None:
    op.create_table(
        "ledger_lines",
        sa.Column("id", UUID, nullable=False),
        sa.Column("journal_id", UUID, nullable=False),
        sa.Column("company_id", UUID, nullable=False),
        sa.Column("account_id", UUID, nullable=False),
        sa.Column("vendor_id", UUID),
        sa.Column("debit_minor", sa.Integer(), nullable=False),
        sa.Column("credit_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("memo", sa.Text()),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["journal_id"],
            ["ledger_journals.id"],
            name="fk_ledger_lines_journal_id_ledger_journals",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name="fk_ledger_lines_company_id_companies"
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["ledger_accounts.id"],
            name="fk_ledger_lines_account_id_ledger_accounts",
        ),
        sa.ForeignKeyConstraint(
            ["vendor_id"], ["vendors.id"], name="fk_ledger_lines_vendor_id_vendors"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ledger_lines"),
    )


def _create_vendor_inventory_balances() -> None:
    op.create_table(
        "vendor_inventory_balances",
        sa.Column("id", UUID, nullable=False),
        sa.Column("company_id", UUID, nullable=False),
        sa.Column("vendor_id", UUID, nullable=False),
        sa.Column("product_id", UUID, nullable=False),
        sa.Column("variant_id", UUID),
        sa.Column("variant_key", UUID, nullable=False),
        sa.Column("warehouse_id", UUID, nullable=False),
        sa.Column("ownership_type", sa.String(length=40), nullable=False),
        sa.Column("on_hand_quantity", sa.Integer(), nullable=False),
        sa.Column("reserved_quantity", sa.Integer(), nullable=False),
        sa.Column("available_quantity", sa.Integer(), nullable=False),
        sa.Column("unit_cost_minor", sa.Integer()),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("last_movement_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_vendor_inventory_balances_company_id_companies",
        ),
        sa.ForeignKeyConstraint(
            ["vendor_id"], ["vendors.id"], name="fk_vendor_inventory_balances_vendor_id_vendors"
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="fk_vendor_inventory_balances_product_id_products",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"],
            ["product_variants.id"],
            name="fk_vendor_inventory_balances_variant_id_product_variants",
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"],
            ["warehouses.id"],
            name="fk_vendor_inventory_balances_warehouse_id_warehouses",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_vendor_inventory_balances"),
        sa.UniqueConstraint(
            "company_id",
            "vendor_id",
            "product_id",
            "variant_key",
            "warehouse_id",
            name="uq_vendor_inventory_balances_scope",
        ),
    )


def _create_vendor_inventory_movements() -> None:
    op.create_table(
        "vendor_inventory_movements",
        sa.Column("id", UUID, nullable=False),
        sa.Column("company_id", UUID, nullable=False),
        sa.Column("vendor_id", UUID, nullable=False),
        sa.Column("product_id", UUID, nullable=False),
        sa.Column("variant_id", UUID),
        sa.Column("warehouse_id", UUID, nullable=False),
        sa.Column("movement_type", sa.String(length=40), nullable=False),
        sa.Column("quantity_delta", sa.Integer(), nullable=False),
        sa.Column("quantity_before", sa.Integer(), nullable=False),
        sa.Column("quantity_after", sa.Integer(), nullable=False),
        sa.Column("reserved_quantity_delta", sa.Integer(), nullable=False),
        sa.Column("ownership_type", sa.String(length=40), nullable=False),
        sa.Column("unit_cost_minor", sa.Integer()),
        sa.Column("valuation_minor", sa.Integer()),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("source_type", sa.String(length=80), nullable=False),
        sa.Column("source_id", sa.String(length=120), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("transfer_group_id", UUID),
        sa.Column("created_by_id", UUID),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_vendor_inventory_movements_company_id_companies",
        ),
        sa.ForeignKeyConstraint(
            ["vendor_id"], ["vendors.id"], name="fk_vendor_inventory_movements_vendor_id_vendors"
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="fk_vendor_inventory_movements_product_id_products",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"],
            ["product_variants.id"],
            name="fk_vendor_inventory_movements_variant_id_product_variants",
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"],
            ["warehouses.id"],
            name="fk_vendor_inventory_movements_warehouse_id_warehouses",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_vendor_inventory_movements_created_by_id_users",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_vendor_inventory_movements"),
        sa.UniqueConstraint(
            "company_id",
            "idempotency_key",
            name="uq_vendor_inventory_movements_company_idempotency_key",
        ),
    )


CREATE_TABLE = {
    "ledger_accounts": _create_ledger_accounts,
    "ledger_periods": _create_ledger_periods,
    "ledger_journals": _create_ledger_journals,
    "ledger_lines": _create_ledger_lines,
    "vendor_inventory_balances": _create_vendor_inventory_balances,
    "vendor_inventory_movements": _create_vendor_inventory_movements,
}


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table_name in RUNTIME_TABLES:
        if table_name not in existing:
            CREATE_TABLE[table_name]()


def downgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table_name in reversed(RUNTIME_TABLES):
        if table_name in existing:
            op.drop_table(table_name)
