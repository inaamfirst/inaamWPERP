"""marketplace and accounting foundation

Revision ID: 202607010008
Revises: 202607010007
Create Date: 2026-07-01 00:00:07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "202607010008"
down_revision = "202607010007"
branch_labels = None
depends_on = None

UUID = sa.String(length=36)
SHORT = sa.String(length=40)
MEDIUM = sa.String(length=120)
LONG = sa.String(length=255)
JSON = sa.JSON()
NOW = sa.text("CURRENT_TIMESTAMP")


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "vendors",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("legal_name", sa.String(length=255)),
        sa.Column("contact_name", sa.String(length=255)),
        sa.Column("email", sa.String(length=255)),
        sa.Column("phone", sa.String(length=80)),
        sa.Column("status", SHORT, nullable=False, server_default="pending"),
        sa.Column("default_commission_bps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata", JSON, nullable=False, server_default=sa.text("'{}'")),
        *timestamps(),
        sa.UniqueConstraint("company_id", "slug"),
    )
    op.create_index("ix_vendors_company_status", "vendors", ["company_id", "status"])

    bind = op.get_bind()

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("products") as batch:
            batch.add_column(sa.Column("vendor_id", UUID, nullable=True))
            batch.create_foreign_key(
                "fk_products_vendor_id_vendors",
                "vendors",
                ["vendor_id"],
                ["id"],
            )
        with op.batch_alter_table("order_items") as batch:
            batch.add_column(sa.Column("vendor_id", UUID, nullable=True))
            batch.create_foreign_key(
                "fk_order_items_vendor_id_vendors",
                "vendors",
                ["vendor_id"],
                ["id"],
            )
    else:
        op.add_column("products", sa.Column("vendor_id", UUID, nullable=True))
        op.create_foreign_key(
            "fk_products_vendor_id_vendors",
            "products",
            "vendors",
            ["vendor_id"],
            ["id"],
        )
        op.add_column("order_items", sa.Column("vendor_id", UUID, nullable=True))
        op.create_foreign_key(
            "fk_order_items_vendor_id_vendors",
            "order_items",
            "vendors",
            ["vendor_id"],
            ["id"],
        )

    op.create_index("ix_products_company_vendor", "products", ["company_id", "vendor_id"])
    op.create_index(
        "ix_order_items_company_vendor",
        "order_items",
        ["company_id", "vendor_id"],
    )

    op.create_table(
        "vendor_users",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("vendor_id", UUID, sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role_name", sa.String(length=80), nullable=False, server_default="vendor"),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("metadata", JSON, nullable=False, server_default=sa.text("'{}'")),
        *timestamps(),
        sa.UniqueConstraint("company_id", "vendor_id", "user_id"),
    )
    op.create_index("ix_vendor_users_vendor_id", "vendor_users", ["vendor_id"])

    op.create_table(
        "marketplace_commission_rules",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("vendor_id", UUID, sa.ForeignKey("vendors.id")),
        sa.Column("category_id", UUID, sa.ForeignKey("categories.id")),
        sa.Column("product_id", UUID, sa.ForeignKey("products.id")),
        sa.Column("commission_bps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("metadata", JSON, nullable=False, server_default=sa.text("'{}'")),
        *timestamps(),
    )
    op.create_index(
        "ix_marketplace_commission_rules_company_vendor",
        "marketplace_commission_rules",
        ["company_id", "vendor_id"],
    )

    op.create_table(
        "accounts",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("account_type", sa.String(length=40), nullable=False),
        sa.Column("parent_id", UUID, sa.ForeignKey("accounts.id")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("metadata", JSON, nullable=False, server_default=sa.text("'{}'")),
        *timestamps(),
        sa.UniqueConstraint("company_id", "code"),
    )

    op.create_table(
        "journal_entries",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("entry_number", sa.String(length=80), nullable=False),
        sa.Column("source_type", SHORT),
        sa.Column("source_id", sa.String(length=120)),
        sa.Column("memo", sa.Text()),
        sa.Column("status", SHORT, nullable=False, server_default="posted"),
        sa.Column("posted_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_id", UUID, sa.ForeignKey("users.id")),
        sa.Column("metadata", JSON, nullable=False, server_default=sa.text("'{}'")),
        *timestamps(),
        sa.UniqueConstraint("company_id", "entry_number"),
    )
    op.create_index(
        "ix_journal_entries_company_status",
        "journal_entries",
        ["company_id", "status"],
    )

    op.create_table(
        "journal_lines",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("journal_entry_id", UUID, sa.ForeignKey("journal_entries.id"), nullable=False),
        sa.Column("account_id", UUID, sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("debit_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("credit_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("memo", sa.Text()),
        sa.Column("metadata", JSON, nullable=False, server_default=sa.text("'{}'")),
    )
    op.create_index("ix_journal_lines_journal_entry_id", "journal_lines", ["journal_entry_id"])

    op.create_table(
        "accounting_periods",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", SHORT, nullable=False, server_default="open"),
        sa.Column("locked_at", sa.DateTime(timezone=True)),
        sa.Column("metadata", JSON, nullable=False, server_default=sa.text("'{}'")),
        *timestamps(),
        sa.UniqueConstraint("company_id", "name"),
    )
    op.create_index(
        "ix_accounting_periods_company_status",
        "accounting_periods",
        ["company_id", "status"],
    )

    op.create_table(
        "cash_books",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="PKR"),
        sa.Column("opening_balance_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("metadata", JSON, nullable=False, server_default=sa.text("'{}'")),
        *timestamps(),
        sa.UniqueConstraint("company_id", "code"),
    )

    op.create_table(
        "bank_accounts",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("bank_name", sa.String(length=255), nullable=False),
        sa.Column("account_name", sa.String(length=255), nullable=False),
        sa.Column("account_number", sa.String(length=120)),
        sa.Column("iban", sa.String(length=80)),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="PKR"),
        sa.Column("opening_balance_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("metadata", JSON, nullable=False, server_default=sa.text("'{}'")),
        *timestamps(),
        sa.UniqueConstraint("company_id", "code"),
    )

    op.create_table(
        "vendor_ledger_entries",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("vendor_id", UUID, sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("entry_type", SHORT, nullable=False),
        sa.Column("source_type", sa.String(length=80)),
        sa.Column("source_id", sa.String(length=120)),
        sa.Column("amount_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("balance_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("memo", sa.Text()),
        sa.Column("metadata", JSON, nullable=False, server_default=sa.text("'{}'")),
        *timestamps(),
    )
    op.create_index(
        "ix_vendor_ledger_entries_company_vendor",
        "vendor_ledger_entries",
        ["company_id", "vendor_id"],
    )

    op.create_table(
        "vendor_settlements",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("vendor_id", UUID, sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("settlement_number", sa.String(length=80), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="PKR"),
        sa.Column("period_start_at", sa.DateTime(timezone=True)),
        sa.Column("period_end_at", sa.DateTime(timezone=True)),
        sa.Column("status", SHORT, nullable=False, server_default="draft"),
        sa.Column("gross_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("commission_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payable_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("paid_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payment_reference", sa.String(length=160)),
        sa.Column("journal_entry_id", UUID, sa.ForeignKey("journal_entries.id")),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("metadata", JSON, nullable=False, server_default=sa.text("'{}'")),
        *timestamps(),
        sa.UniqueConstraint("company_id", "vendor_id", "settlement_number"),
    )
    op.create_index(
        "ix_vendor_settlements_company_vendor_status",
        "vendor_settlements",
        ["company_id", "vendor_id", "status"],
    )

    op.create_table(
        "vendor_products",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("vendor_id", UUID, sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("product_id", UUID, sa.ForeignKey("products.id"), nullable=False),
        sa.Column("approval_status", SHORT, nullable=False, server_default="submitted"),
        sa.Column("approved_by_id", UUID, sa.ForeignKey("users.id")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("rejected_reason", sa.Text()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("metadata", JSON, nullable=False, server_default=sa.text("'{}'")),
        *timestamps(),
        sa.UniqueConstraint("company_id", "product_id"),
    )
    op.create_index(
        "ix_vendor_products_company_vendor_status",
        "vendor_products",
        ["company_id", "vendor_id", "approval_status"],
    )

    op.create_table(
        "vendor_order_items",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("vendor_id", UUID, sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("order_id", UUID, sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("order_item_id", UUID, sa.ForeignKey("order_items.id"), nullable=False),
        sa.Column("product_id", UUID, sa.ForeignKey("products.id"), nullable=False),
        sa.Column("variant_id", UUID, sa.ForeignKey("product_variants.id")),
        sa.Column("sku", MEDIUM),
        sa.Column("name", LONG, nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price_minor", sa.Integer(), nullable=False),
        sa.Column("line_total_minor", sa.Integer(), nullable=False),
        sa.Column("commission_bps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("commission_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payable_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", SHORT, nullable=False, server_default="pending"),
        sa.Column("settlement_id", UUID, sa.ForeignKey("vendor_settlements.id")),
        sa.Column("metadata", JSON, nullable=False, server_default=sa.text("'{}'")),
        *timestamps(),
        sa.UniqueConstraint("company_id", "order_item_id"),
    )
    op.create_index(
        "ix_vendor_order_items_company_vendor_created_at",
        "vendor_order_items",
        ["company_id", "vendor_id", "created_at"],
    )

    op.create_table(
        "vendor_notifications",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("vendor_id", UUID, sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("channel", SHORT, nullable=False, server_default="in_app"),
        sa.Column("notification_type", sa.String(length=80), nullable=False),
        sa.Column("subject", sa.String(length=255)),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", SHORT, nullable=False, server_default="queued"),
        sa.Column("metadata", JSON, nullable=False, server_default=sa.text("'{}'")),
        *timestamps(),
    )
    op.create_index(
        "ix_vendor_notifications_company_vendor_status",
        "vendor_notifications",
        ["company_id", "vendor_id", "status"],
    )

    op.create_table(
        "expenses",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("expense_number", sa.String(length=80), nullable=False),
        sa.Column("account_id", UUID, sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("vendor_id", UUID, sa.ForeignKey("vendors.id")),
        sa.Column("cash_book_id", UUID, sa.ForeignKey("cash_books.id")),
        sa.Column("bank_account_id", UUID, sa.ForeignKey("bank_accounts.id")),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="PKR"),
        sa.Column("status", SHORT, nullable=False, server_default="draft"),
        sa.Column("memo", sa.Text()),
        sa.Column("incurred_at", sa.DateTime(timezone=True)),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("metadata", JSON, nullable=False, server_default=sa.text("'{}'")),
        *timestamps(),
        sa.UniqueConstraint("company_id", "expense_number"),
    )
    op.create_index("ix_expenses_company_status", "expenses", ["company_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_expenses_company_status", table_name="expenses")
    op.drop_table("expenses")
    op.drop_index(
        "ix_vendor_notifications_company_vendor_status",
        table_name="vendor_notifications",
    )
    op.drop_table("vendor_notifications")
    op.drop_index(
        "ix_vendor_order_items_company_vendor_created_at",
        table_name="vendor_order_items",
    )
    op.drop_table("vendor_order_items")
    op.drop_index(
        "ix_vendor_products_company_vendor_status",
        table_name="vendor_products",
    )
    op.drop_table("vendor_products")
    op.drop_index(
        "ix_vendor_settlements_company_vendor_status",
        table_name="vendor_settlements",
    )
    op.drop_table("vendor_settlements")
    op.drop_index(
        "ix_vendor_ledger_entries_company_vendor",
        table_name="vendor_ledger_entries",
    )
    op.drop_table("vendor_ledger_entries")
    op.drop_table("bank_accounts")
    op.drop_table("cash_books")
    op.drop_index(
        "ix_accounting_periods_company_status",
        table_name="accounting_periods",
    )
    op.drop_table("accounting_periods")
    op.drop_index("ix_journal_lines_journal_entry_id", table_name="journal_lines")
    op.drop_table("journal_lines")
    op.drop_table("accounts")
    op.drop_index("ix_journal_entries_company_status", table_name="journal_entries")
    op.drop_table("journal_entries")
    op.drop_index(
        "ix_marketplace_commission_rules_company_vendor",
        table_name="marketplace_commission_rules",
    )
    op.drop_table("marketplace_commission_rules")
    op.drop_index("ix_vendor_users_vendor_id", table_name="vendor_users")
    op.drop_table("vendor_users")
    op.drop_index("ix_vendors_company_status", table_name="vendors")
    op.drop_table("vendors")
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("order_items") as batch:
            batch.drop_constraint("fk_order_items_vendor_id_vendors", type_="foreignkey")
            batch.drop_column("vendor_id")
        with op.batch_alter_table("products") as batch:
            batch.drop_constraint("fk_products_vendor_id_vendors", type_="foreignkey")
            batch.drop_column("vendor_id")
    else:
        op.drop_constraint("fk_order_items_vendor_id_vendors", "order_items", type_="foreignkey")
        op.drop_column("order_items", "vendor_id")
        op.drop_constraint("fk_products_vendor_id_vendors", "products", type_="foreignkey")
        op.drop_column("products", "vendor_id")
    op.drop_index("ix_order_items_company_vendor", table_name="order_items")
    op.drop_index("ix_products_company_vendor", table_name="products")
