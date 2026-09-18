from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session

from erp.packages.core.db import models as _models  # noqa: F401
from erp.packages.core.db.base import Base
from erp.packages.core.diagnostics_services import (
    expected_migration_revision,
    is_database_migration_current,
)
from erp.packages.core.services import MANAGER_CORE_PERMISSIONS

AUTH_TABLES = {
    "auth_refresh_tokens",
    "auth_action_tokens",
    "login_throttles",
}
RUNTIME_SCHEMA_TABLES = {
    "ledger_accounts",
    "ledger_periods",
    "ledger_journals",
    "ledger_lines",
    "vendor_inventory_balances",
    "vendor_inventory_movements",
}
USER_AUTH_COLUMNS = {
    "account_status",
    "must_change_password",
    "password_changed_at",
    "last_login_at",
}
VENDOR_SELF_PERMISSIONS = {
    "vendor.profile.view",
    "vendor.products.view",
    "vendor.products.manage",
    "vendor.orders.view",
    "vendor.orders.manage",
    "vendor.settlements.view",
    "vendor.ledger.view",
    "vendor.stock.view",
    "vendor.stock.manage",
    "vendor.reports.view",
}
PRESERVED_TABLES = (
    "users",
    "auth_sessions",
    "vendors",
    "products",
    "warehouses",
    "stock_movements",
    "accounts",
    "journal_entries",
    "journal_lines",
    "vendor_ledger_entries",
    "vendor_settlements",
)


def migration_config(root: Path, database_url: str) -> Config:
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    # Alembic stores options in ConfigParser, where URL-encoded percent signs
    # must be escaped to survive interpolation unchanged.
    cfg.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return cfg


def table_names(engine: sa.Engine) -> set[str]:
    return set(sa.inspect(engine).get_table_names())


def assert_auth_only_schema(engine: sa.Engine) -> None:
    inspector = sa.inspect(engine)
    tables = set(inspector.get_table_names())
    assert AUTH_TABLES.issubset(tables)
    assert not (RUNTIME_SCHEMA_TABLES & tables)
    assert not any(name.startswith("ledger_") for name in tables)
    assert not any(name.startswith("vendor_inventory_") for name in tables)

    user_columns = {column["name"] for column in inspector.get_columns("users")}
    vendor_product_columns = {column["name"] for column in inspector.get_columns("vendor_products")}
    assert USER_AUTH_COLUMNS.issubset(user_columns)
    assert "ownership_type" in vendor_product_columns

    refresh_pk = inspector.get_pk_constraint("auth_refresh_tokens")
    refresh_unique = {
        row["name"] for row in inspector.get_unique_constraints("auth_refresh_tokens")
    }
    refresh_fks = {row["name"] for row in inspector.get_foreign_keys("auth_refresh_tokens")}
    assert refresh_pk["name"] == "pk_auth_refresh_tokens"
    assert "uq_auth_refresh_tokens_token_hash" in refresh_unique
    assert {
        "fk_auth_refresh_tokens_user_id_users",
        "fk_auth_refresh_tokens_session_id_auth_sessions",
        "fk_auth_refresh_tokens_replaced_by_id_auth_refresh_tokens",
    }.issubset(refresh_fks)

    action_pk = inspector.get_pk_constraint("auth_action_tokens")
    action_unique = {row["name"] for row in inspector.get_unique_constraints("auth_action_tokens")}
    action_fks = {row["name"] for row in inspector.get_foreign_keys("auth_action_tokens")}
    assert action_pk["name"] == "pk_auth_action_tokens"
    assert "uq_auth_action_tokens_token_hash" in action_unique
    assert "fk_auth_action_tokens_user_id_users" in action_fks

    throttle_pk = inspector.get_pk_constraint("login_throttles")
    throttle_unique = {row["name"] for row in inspector.get_unique_constraints("login_throttles")}
    assert throttle_pk["name"] == "pk_login_throttles"
    assert "uq_login_throttles_scope_key" in throttle_unique


def assert_head_schema(engine: sa.Engine) -> None:
    inspector = sa.inspect(engine)
    tables = set(inspector.get_table_names())
    assert AUTH_TABLES.issubset(tables)
    assert RUNTIME_SCHEMA_TABLES.issubset(tables)
    product_video_columns = {
        column["name"] for column in inspector.get_columns("product_videos")
    }
    assert {
        "external_id",
        "remote_url",
        "sync_status",
        "last_synced_at",
    }.issubset(product_video_columns)

    expected_unique_constraints = {
        "ledger_accounts": {"uq_ledger_accounts_company_code"},
        "ledger_periods": {"uq_ledger_periods_company_name"},
        "ledger_journals": {
            "uq_ledger_journals_company_entry_number",
            "uq_ledger_journals_company_idempotency_key",
        },
        "vendor_inventory_balances": {"uq_vendor_inventory_balances_scope"},
        "vendor_inventory_movements": {
            "uq_vendor_inventory_movements_company_idempotency_key"
        },
    }
    for table_name, expected_names in expected_unique_constraints.items():
        actual_names = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints(table_name)
        }
        assert expected_names.issubset(actual_names)


def _ids() -> dict[str, str]:
    return {
        name: str(uuid.uuid4())
        for name in (
            "company",
            "admin_user",
            "vendor_user",
            "inactive_user",
            "session",
            "vendor",
            "vendor_link",
            "admin_role",
            "existing_permission",
            "product",
            "warehouse",
            "stock_movement",
            "account",
            "journal",
            "line",
            "vendor_entry",
            "settlement",
        )
    }


def seed_legacy_data(engine: sa.Engine) -> dict[str, str]:
    ids = _ids()
    expires_at = datetime.now(UTC) + timedelta(days=1)
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO companies (id, name, slug, status) "
                "VALUES (:id, 'Legacy Company', 'legacy-company', 'active')"
            ),
            {"id": ids["company"]},
        )
        connection.execute(
            sa.text(
                "INSERT INTO users "
                "(id, company_id, username, email, password_hash, is_active) VALUES "
                "(:admin, :company, 'legacy-admin', 'admin@example.test', "
                "'admin-hash', true), "
                "(:vendor_user, :company, 'legacy-vendor-user', "
                "'vendor@example.test', 'vendor-hash', true), "
                "(:inactive, :company, 'legacy-inactive', "
                "'inactive@example.test', 'inactive-hash', false)"
            ),
            {
                "admin": ids["admin_user"],
                "vendor_user": ids["vendor_user"],
                "inactive": ids["inactive_user"],
                "company": ids["company"],
            },
        )
        connection.execute(
            sa.text(
                "INSERT INTO auth_sessions "
                "(id, user_id, token_hash, user_agent, expires_at) "
                "VALUES (:id, :user_id, 'legacy-session-hash', 'legacy-client', :expires_at)"
            ),
            {
                "id": ids["session"],
                "user_id": ids["admin_user"],
                "expires_at": expires_at,
            },
        )
        connection.execute(
            sa.text(
                "INSERT INTO roles (id, company_id, name, description) "
                "VALUES (:id, :company, 'Administrator', 'Legacy administrator')"
            ),
            {"id": ids["admin_role"], "company": ids["company"]},
        )
        connection.execute(
            sa.text(
                "INSERT INTO permissions (id, key, description) "
                "VALUES (:id, 'existing.permission', 'Existing permission')"
            ),
            {"id": ids["existing_permission"]},
        )
        connection.execute(
            sa.text(
                "INSERT INTO role_permissions (role_id, permission_id) VALUES (:role, :permission)"
            ),
            {
                "role": ids["admin_role"],
                "permission": ids["existing_permission"],
            },
        )
        connection.execute(
            sa.text("INSERT INTO user_roles (user_id, role_id) VALUES (:user, :role)"),
            {"user": ids["admin_user"], "role": ids["admin_role"]},
        )
        connection.execute(
            sa.text(
                "INSERT INTO vendors "
                "(id, company_id, name, slug, status, default_commission_bps, metadata) "
                "VALUES (:id, :company, 'Legacy Vendor', 'legacy-vendor', "
                "'approved', 500, '{}')"
            ),
            {"id": ids["vendor"], "company": ids["company"]},
        )
        connection.execute(
            sa.text(
                "INSERT INTO vendor_users "
                "(id, company_id, vendor_id, user_id, role_name, is_primary, metadata) "
                "VALUES (:id, :company, :vendor, :user, 'vendor', false, '{}')"
            ),
            {
                "id": ids["vendor_link"],
                "company": ids["company"],
                "vendor": ids["vendor"],
                "user": ids["vendor_user"],
            },
        )
        connection.execute(
            sa.text(
                "INSERT INTO products (id, company_id, name, slug, status, metadata) "
                "VALUES (:id, :company, 'Legacy Product', 'legacy-product', 'active', '{}')"
            ),
            {"id": ids["product"], "company": ids["company"]},
        )
        connection.execute(
            sa.text(
                "INSERT INTO warehouses (id, company_id, code, name, is_active) "
                "VALUES (:id, :company, 'MAIN', 'Main Warehouse', true)"
            ),
            {"id": ids["warehouse"], "company": ids["company"]},
        )
        connection.execute(
            sa.text(
                "INSERT INTO stock_movements "
                "(id, company_id, warehouse_id, product_id, movement_type, "
                "quantity_delta, reference_type, reference_id, metadata, created_by_id) "
                "VALUES (:id, :company, :warehouse, :product, 'opening', 7, "
                "'legacy', 'stock-1', '{}', :created_by)"
            ),
            {
                "id": ids["stock_movement"],
                "company": ids["company"],
                "warehouse": ids["warehouse"],
                "product": ids["product"],
                "created_by": ids["admin_user"],
            },
        )
        connection.execute(
            sa.text(
                "INSERT INTO accounts "
                "(id, company_id, code, name, account_type, is_active, metadata) "
                "VALUES (:id, :company, '2000', 'Vendor Payable', "
                "'liability', true, '{}')"
            ),
            {"id": ids["account"], "company": ids["company"]},
        )
        connection.execute(
            sa.text(
                "INSERT INTO journal_entries "
                "(id, company_id, entry_number, source_type, source_id, memo, status, "
                "posted_at, created_by_id, metadata) "
                "VALUES (:id, :company, 'JE-LEGACY', 'payment', 'payment-1', "
                "'Legacy journal', 'posted', CURRENT_TIMESTAMP, :created_by, '{}')"
            ),
            {
                "id": ids["journal"],
                "company": ids["company"],
                "created_by": ids["admin_user"],
            },
        )
        connection.execute(
            sa.text(
                "INSERT INTO journal_lines "
                "(id, company_id, journal_entry_id, account_id, debit_minor, "
                "credit_minor, memo, metadata) "
                "VALUES (:id, :company, :journal, :account, 0, 500, "
                "'Legacy line', '{}')"
            ),
            {
                "id": ids["line"],
                "company": ids["company"],
                "journal": ids["journal"],
                "account": ids["account"],
            },
        )
        connection.execute(
            sa.text(
                "INSERT INTO vendor_ledger_entries "
                "(id, company_id, vendor_id, entry_type, source_type, source_id, "
                "amount_minor, balance_minor, memo, metadata) "
                "VALUES (:id, :company, :vendor, 'sale', 'payment', 'payment-1', "
                "500, 500, 'Legacy payable', '{}')"
            ),
            {
                "id": ids["vendor_entry"],
                "company": ids["company"],
                "vendor": ids["vendor"],
            },
        )
        connection.execute(
            sa.text(
                "INSERT INTO vendor_settlements "
                "(id, company_id, vendor_id, settlement_number, currency, status, "
                "gross_minor, commission_minor, payable_minor, paid_minor, metadata) "
                "VALUES (:id, :company, :vendor, 'SET-LEGACY', 'PKR', 'paid', "
                "500, 50, 450, 450, '{}')"
            ),
            {
                "id": ids["settlement"],
                "company": ids["company"],
                "vendor": ids["vendor"],
            },
        )
    return ids


def preserved_layout(engine: sa.Engine) -> dict[str, tuple[str, ...]]:
    inspector = sa.inspect(engine)
    return {
        table: tuple(column["name"] for column in inspector.get_columns(table))
        for table in PRESERVED_TABLES
    }


def preserved_snapshot(
    engine: sa.Engine,
    layout: dict[str, tuple[str, ...]],
) -> dict[str, list[dict[str, object]]]:
    result: dict[str, list[dict[str, object]]] = {}
    with engine.connect() as connection:
        for table_name, column_names in layout.items():
            metadata = sa.MetaData()
            table = sa.Table(table_name, metadata, autoload_with=connection)
            columns = [table.c[name] for name in column_names]
            order_columns = list(table.primary_key.columns) or columns[:1]
            result[table_name] = [
                dict(row)
                for row in connection.execute(
                    sa.select(*columns).order_by(*order_columns)
                ).mappings()
            ]
    return result


def assert_vendor_backfill(engine: sa.Engine, ids: dict[str, str]) -> None:
    with engine.connect() as connection:
        vendor_status = connection.execute(
            sa.text("SELECT status FROM vendors WHERE id = :id"),
            {"id": ids["vendor"]},
        ).scalar_one()
        account_statuses = dict(
            connection.execute(sa.text("SELECT username, account_status FROM users")).all()
        )
        primary = connection.execute(
            sa.text("SELECT is_primary FROM vendor_users WHERE id = :id"),
            {"id": ids["vendor_link"]},
        ).scalar_one()
        role_permissions = set(
            connection.execute(
                sa.text(
                    "SELECT p.key FROM roles r "
                    "JOIN role_permissions rp ON rp.role_id = r.id "
                    "JOIN permissions p ON p.id = rp.permission_id "
                    "WHERE r.company_id = :company AND r.name = 'Vendor'"
                ),
                {"company": ids["company"]},
            ).scalars()
        )
        vendor_role_users = set(
            connection.execute(
                sa.text(
                    "SELECT ur.user_id FROM roles r "
                    "JOIN user_roles ur ON ur.role_id = r.id "
                    "WHERE r.company_id = :company AND r.name = 'Vendor'"
                ),
                {"company": ids["company"]},
            ).scalars()
        )

    assert vendor_status == "approved"
    assert account_statuses["legacy-admin"] == "active"
    assert account_statuses["legacy-vendor-user"] == "active"
    assert account_statuses["legacy-inactive"] == "stopped"
    assert bool(primary) is True
    assert role_permissions == VENDOR_SELF_PERMISSIONS
    assert vendor_role_users == {ids["vendor_user"]}


def run_roundtrip(root: Path, database_url: str) -> None:
    cfg = migration_config(root, database_url)
    command.upgrade(cfg, "202607010013")
    engine = sa.create_engine(database_url, future=True)
    try:
        ids = seed_legacy_data(engine)
        layout = preserved_layout(engine)
        before = preserved_snapshot(engine, layout)

        command.upgrade(cfg, "head")
        assert_head_schema(engine)
        assert preserved_snapshot(engine, layout) == before
        assert_vendor_backfill(engine, ids)

        command.downgrade(cfg, "202607010013")
        downgraded_tables = table_names(engine)
        assert not (AUTH_TABLES & downgraded_tables)
        downgraded_user_columns = {
            column["name"] for column in sa.inspect(engine).get_columns("users")
        }
        assert not (USER_AUTH_COLUMNS & downgraded_user_columns)
        assert preserved_snapshot(engine, layout) == before

        command.upgrade(cfg, "head")
        assert_head_schema(engine)
        assert preserved_snapshot(engine, layout) == before
        assert_vendor_backfill(engine, ids)
    finally:
        engine.dispose()


def test_product_video_sync_migration_preserves_existing_rows(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite:///{tmp_path / 'product_video_sync.db'}"
    cfg = migration_config(root, database_url)
    command.upgrade(cfg, "202609020025")
    engine = sa.create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    "INSERT INTO companies (id, name, slug, status) "
                    "VALUES ('company-video', 'Video Company', 'video-company', 'active')"
                )
            )
            connection.execute(
                sa.text(
                    "INSERT INTO products "
                    "(id, company_id, name, slug, product_type, status, metadata) VALUES "
                    "('product-video', 'company-video', 'Demo product', 'demo-product', "
                    "'simple', 'active', '{}')"
                )
            )
            connection.execute(
                sa.text(
                    "INSERT INTO product_videos "
                    "(id, company_id, product_id, source_type, url, name, sort_order) VALUES "
                    "('video-legacy', 'company-video', 'product-video', 'youtube', "
                    "'https://www.youtube.com/watch?v=abc123XYZ', 'Legacy demo', 0)"
                )
            )

        command.upgrade(cfg, "head")
        with engine.connect() as connection:
            row = connection.execute(
                sa.text(
                    "SELECT source_type, url, name, sort_order, external_id, remote_url, "
                    "sync_status FROM product_videos WHERE id = 'video-legacy'"
                )
            ).mappings().one()
        assert dict(row) == {
            "source_type": "youtube",
            "url": "https://www.youtube.com/watch?v=abc123XYZ",
            "name": "Legacy demo",
            "sort_order": 0,
            "external_id": None,
            "remote_url": None,
            "sync_status": "pending_add",
        }

        command.downgrade(cfg, "202609020025")
        with engine.connect() as connection:
            columns = {
                column["name"]
                for column in sa.inspect(engine).get_columns("product_videos")
            }
            row = connection.execute(
                sa.text("SELECT url, name FROM product_videos WHERE id = 'video-legacy'")
            ).mappings().one()
        assert {"external_id", "remote_url", "sync_status", "last_synced_at"}.isdisjoint(columns)
        assert dict(row) == {
            "url": "https://www.youtube.com/watch?v=abc123XYZ",
            "name": "Legacy demo",
        }
    finally:
        engine.dispose()


def seed_ambiguous_vendor_links(engine: sa.Engine) -> None:
    ids = {
        name: str(uuid.uuid4())
        for name in ("company", "user", "vendor_a", "vendor_b", "link_a", "link_b")
    }
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO companies (id, name, slug, status) "
                "VALUES (:id, 'Ambiguous Company', 'ambiguous-company', 'active')"
            ),
            {"id": ids["company"]},
        )
        connection.execute(
            sa.text(
                "INSERT INTO users (id, company_id, username, password_hash, is_active) "
                "VALUES (:id, :company, 'ambiguous-vendor', 'hash', true)"
            ),
            {"id": ids["user"], "company": ids["company"]},
        )
        connection.execute(
            sa.text(
                "INSERT INTO vendors "
                "(id, company_id, name, slug, status, default_commission_bps, metadata) "
                "VALUES (:a, :company, 'Vendor A', 'vendor-a', 'approved', 0, '{}'), "
                "(:b, :company, 'Vendor B', 'vendor-b', 'approved', 0, '{}')"
            ),
            {
                "a": ids["vendor_a"],
                "b": ids["vendor_b"],
                "company": ids["company"],
            },
        )
        connection.execute(
            sa.text(
                "INSERT INTO vendor_users "
                "(id, company_id, vendor_id, user_id, role_name, is_primary, metadata) "
                "VALUES (:link_a, :company, :vendor_a, :user, 'vendor', false, '{}'), "
                "(:link_b, :company, :vendor_b, :user, 'vendor', false, '{}')"
            ),
            {
                "link_a": ids["link_a"],
                "link_b": ids["link_b"],
                "company": ids["company"],
                "vendor_a": ids["vendor_a"],
                "vendor_b": ids["vendor_b"],
                "user": ids["user"],
            },
        )


def run_ambiguous_preflight(root: Path, database_url: str) -> None:
    cfg = migration_config(root, database_url)
    command.upgrade(cfg, "202607010013")
    engine = sa.create_engine(database_url, future=True)
    try:
        seed_ambiguous_vendor_links(engine)
        with pytest.raises(Exception, match="ambiguous VendorUser primary"):
            command.upgrade(cfg, "202607010014")
        assert not (AUTH_TABLES & table_names(engine))
        user_columns = {column["name"] for column in sa.inspect(engine).get_columns("users")}
        assert not (USER_AUTH_COLUMNS & user_columns)
        with engine.connect() as connection:
            revision = connection.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        assert revision == "202607010013"
    finally:
        engine.dispose()


def _postgres_test_url() -> str | None:
    value = os.environ.get("ERP_TEST_POSTGRES_URL", "").strip()
    return value or None


@pytest.fixture
def disposable_postgres_url() -> Iterator[str]:
    configured = _postgres_test_url()
    if not configured:
        pytest.skip("ERP_TEST_POSTGRES_URL is not configured")
    url = make_url(configured)
    if not url.drivername.startswith("postgresql"):
        pytest.fail("ERP_TEST_POSTGRES_URL must use PostgreSQL")

    schema = f"phase1_migration_{uuid.uuid4().hex}"
    assert re.fullmatch(r"phase1_migration_[0-9a-f]{32}", schema)
    admin_engine = sa.create_engine(configured, future=True)
    quoted_schema = admin_engine.dialect.identifier_preparer.quote_schema(schema)
    with admin_engine.begin() as connection:
        connection.execute(sa.text(f"CREATE SCHEMA {quoted_schema}"))

    query = dict(url.query)
    query["options"] = f"-csearch_path={schema}"
    scoped_url: URL = url.set(query=query)
    try:
        yield scoped_url.render_as_string(hide_password=False)
    finally:
        with admin_engine.begin() as connection:
            connection.execute(sa.text(f"DROP SCHEMA {quoted_schema} CASCADE"))
        admin_engine.dispose()


def test_auth_vendor_migration_remains_scoped_on_sqlite(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite:///{tmp_path / 'auth-scope.db'}"
    cfg = migration_config(root, database_url)

    command.upgrade(cfg, "202607010015")
    engine = sa.create_engine(database_url, future=True)
    try:
        assert_auth_only_schema(engine)
    finally:
        engine.dispose()


def test_fresh_installation_matches_runtime_schema_on_sqlite(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "fresh_install.db"
    database_url = f"sqlite:///{database_path}"
    cfg = migration_config(root, database_url)

    command.upgrade(cfg, "head")
    engine = sa.create_engine(database_url, future=True)
    try:
        assert_head_schema(engine)
    finally:
        engine.dispose()


def test_vendor_shop_shared_stock_migration_moves_only_remaining_woo_balance_once(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite:///{tmp_path / 'vendor-shop-shared-stock.db'}"
    cfg = migration_config(root, database_url)
    command.upgrade(cfg, "202609100028")
    engine = sa.create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(sa.text("INSERT INTO companies (id, name, slug, status) VALUES ('company-stock', 'Stock Company', 'stock-company', 'active')"))
            connection.execute(sa.text("INSERT INTO users (id, company_id, username, password_hash, is_active) VALUES ('user-stock', 'company-stock', 'stock-user', 'hash', true)"))
            connection.execute(sa.text("INSERT INTO vendors (id, company_id, name, slug, status, default_commission_bps, metadata) VALUES ('vendor-stock', 'company-stock', 'Stock Vendor', 'stock-vendor', 'approved', 0, '{}')"))
            connection.execute(sa.text("INSERT INTO customers (id, company_id, full_name, source_channel, status, credit_limit_minor, metadata) VALUES ('customer-stock', 'company-stock', 'Customer', 'woocommerce', 'active', 0, '{}')"))
            connection.execute(sa.text("INSERT INTO products (id, company_id, vendor_id, name, slug, status, manage_stock, stock_status, metadata) VALUES ('product-stock', 'company-stock', 'vendor-stock', 'Stock Product', 'stock-product', 'active', true, 'instock', '{}')"))
            connection.execute(sa.text("INSERT INTO warehouses (id, company_id, vendor_id, warehouse_type, code, name, is_active) VALUES ('warehouse-woo', 'company-stock', NULL, 'company', 'WOO', 'WooCommerce', true)"))
            connection.execute(sa.text("INSERT INTO stock_movements (id, company_id, warehouse_id, product_id, movement_type, quantity_delta, reference_type, reference_id, metadata, created_by_id) VALUES ('movement-woo', 'company-stock', 'warehouse-woo', 'product-stock', 'opening', 7, 'legacy', 'woo-balance', '{}', 'user-stock')"))
            connection.execute(sa.text("INSERT INTO orders (id, company_id, customer_id, order_number, sales_channel, order_source, reservation_status, status, currency, metadata) VALUES ('order-stock', 'company-stock', 'customer-stock', 'WC-1', 'legacy', 'legacy', 'none', 'confirmed', 'PKR', '{}')"))
            connection.execute(sa.text("INSERT INTO external_resource_map (id, company_id, connector, internal_resource_type, internal_resource_id, external_resource_type, external_resource_id, metadata) VALUES ('map-stock', 'company-stock', 'woocommerce', 'order', 'order-stock', 'order', '123', '{}')"))

        command.upgrade(cfg, "head")
        with engine.connect() as connection:
            shop_warehouse = connection.execute(sa.text("SELECT id FROM warehouses WHERE company_id = 'company-stock' AND vendor_id = 'vendor-stock' AND warehouse_type = 'vendor_shop'" )).scalar_one()
            woo_balance = connection.execute(sa.text("SELECT COALESCE(SUM(quantity_delta), 0) FROM stock_movements WHERE warehouse_id = 'warehouse-woo'" )).scalar_one()
            shop_balance = connection.execute(sa.text("SELECT COALESCE(SUM(quantity_delta), 0) FROM stock_movements WHERE warehouse_id = :warehouse"), {"warehouse": shop_warehouse}).scalar_one()
            order = connection.execute(sa.text("SELECT sales_channel, order_source, reservation_status FROM orders WHERE id = 'order-stock'" )).mappings().one()
            catalog_quantity = connection.execute(sa.text("SELECT stock_quantity FROM products WHERE id = 'product-stock'" )).scalar_one()
        assert woo_balance == 0
        assert shop_balance == 7
        assert dict(order) == {"sales_channel": "woocommerce", "order_source": "woocommerce", "reservation_status": "baseline"}
        assert catalog_quantity == 7

        command.upgrade(cfg, "head")
        with engine.connect() as connection:
            count = connection.execute(sa.text("SELECT COUNT(*) FROM stock_movements WHERE reference_type = 'vendor_shop_baseline_transfer'" )).scalar_one()
        assert count == 2
    finally:
        engine.dispose()


def test_vendor_shop_shared_stock_migration_hashes_long_audit_reference_ids(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite:///{tmp_path / 'vendor-shop-audit-reference.db'}"
    cfg = migration_config(root, database_url)
    command.upgrade(cfg, "202609100028")
    company_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    product_id = str(uuid.uuid4())
    variant_id = str(uuid.uuid4())
    warehouse_id = str(uuid.uuid4())
    engine = sa.create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                sa.text("INSERT INTO companies (id, name, slug, status) VALUES (:id, 'Audit Company', 'audit-company', 'active')"),
                {"id": company_id},
            )
            connection.execute(
                sa.text("INSERT INTO users (id, company_id, username, password_hash, is_active) VALUES (:id, :company_id, 'audit-user', 'hash', true)"),
                {"id": user_id, "company_id": company_id},
            )
            connection.execute(
                sa.text("INSERT INTO products (id, company_id, name, slug, status, manage_stock, stock_status, metadata) VALUES (:id, :company_id, 'Audit Product', 'audit-product', 'active', true, 'instock', '{}')"),
                {"id": product_id, "company_id": company_id},
            )
            connection.execute(
                sa.text("INSERT INTO product_variants (id, company_id, product_id, sku, price_minor, currency, attributes, is_active) VALUES (:id, :company_id, :product_id, 'audit-variant', 0, 'PKR', '{}', true)"),
                {"id": variant_id, "company_id": company_id, "product_id": product_id},
            )
            connection.execute(
                sa.text("INSERT INTO warehouses (id, company_id, vendor_id, warehouse_type, code, name, is_active) VALUES (:id, :company_id, NULL, 'company', 'WOO', 'WooCommerce', true)"),
                {"id": warehouse_id, "company_id": company_id},
            )
            connection.execute(
                sa.text("INSERT INTO stock_movements (id, company_id, warehouse_id, product_id, variant_id, movement_type, quantity_delta, reference_type, reference_id, metadata, created_by_id) VALUES (:id, :company_id, :warehouse_id, :product_id, :variant_id, 'opening', 7, 'legacy', 'woo-balance', '{}', :user_id)"),
                {
                    "id": str(uuid.uuid4()), "company_id": company_id, "warehouse_id": warehouse_id,
                    "product_id": product_id, "variant_id": variant_id, "user_id": user_id,
                },
            )

        command.upgrade(cfg, "head")
        expected_reference = f"woo-baseline:{warehouse_id}:{product_id}:{variant_id}"
        with engine.connect() as connection:
            audit = connection.execute(
                sa.text("SELECT entity_id, metadata FROM audit_logs WHERE company_id = :company_id AND action = 'commerce.vendor_stock_reconciliation_ambiguous'"),
                {"company_id": company_id},
            ).mappings().one()
        audit_metadata = audit["metadata"]
        if isinstance(audit_metadata, str):
            audit_metadata = json.loads(audit_metadata)
        assert len(expected_reference) > 120
        assert audit["entity_id"].startswith("sha256:")
        assert len(audit["entity_id"]) <= 120
        assert audit_metadata["reference_id"] == expected_reference
    finally:
        engine.dispose()


def test_runtime_schema_migration_adopts_existing_tables_on_sqlite(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite:///{tmp_path / 'adopt-existing.db'}"
    cfg = migration_config(root, database_url)
    command.upgrade(cfg, "202608210020")
    engine = sa.create_engine(database_url, future=True)
    try:
        Base.metadata.create_all(
            engine,
            tables=[Base.metadata.tables[name] for name in RUNTIME_SCHEMA_TABLES],
        )
        command.upgrade(cfg, "head")
        assert_head_schema(engine)

        command.downgrade(cfg, "202608210020")
        assert not (RUNTIME_SCHEMA_TABLES & table_names(engine))
        command.upgrade(cfg, "head")
        assert_head_schema(engine)
    finally:
        engine.dispose()


def test_database_readiness_requires_runtime_tables(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite:///{tmp_path / 'readiness.db'}"
    cfg = migration_config(root, database_url)
    command.upgrade(cfg, "head")
    engine = sa.create_engine(database_url, future=True)
    expected_migration_revision.cache_clear()
    try:
        with Session(engine) as db:
            assert is_database_migration_current(db)
        with engine.begin() as connection:
            connection.execute(sa.text("DROP TABLE ledger_lines"))
        with Session(engine) as db:
            assert not is_database_migration_current(db)
    finally:
        engine.dispose()


def test_audit_actor_migration_repairs_orphans_and_sets_delete_policy(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite:///{tmp_path / 'audit-actor.db'}"
    cfg = migration_config(root, database_url)
    command.upgrade(cfg, "202608210021")
    engine = sa.create_engine(database_url, future=True)
    company_id = str(uuid.uuid4())
    audit_id = str(uuid.uuid4())
    try:
        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    "INSERT INTO companies (id, name, slug, status) "
                    "VALUES (:id, 'Audit Company', 'audit-company', 'active')"
                ),
                {"id": company_id},
            )
            connection.execute(
                sa.text(
                    "INSERT INTO audit_logs "
                    "(id, company_id, user_id, action, metadata) "
                    "VALUES (:id, :company_id, 'system', 'system.action', '{}')"
                ),
                {"id": audit_id, "company_id": company_id},
            )

        command.upgrade(cfg, "head")
        with engine.connect() as connection:
            assert connection.execute(
                sa.text("SELECT user_id FROM audit_logs WHERE id = :id"),
                {"id": audit_id},
            ).scalar_one() is None
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        user_fk = next(
            foreign_key
            for foreign_key in sa.inspect(engine).get_foreign_keys("audit_logs")
            if foreign_key["constrained_columns"] == ["user_id"]
        )
        assert user_fk["options"].get("ondelete") == "SET NULL"
    finally:
        engine.dispose()


def test_auth_vendor_migration_roundtrip_preserves_sqlite_data(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    run_roundtrip(root, f"sqlite:///{tmp_path / 'roundtrip.db'}")


def test_auth_vendor_migration_rejects_ambiguous_sqlite_links(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    run_ambiguous_preflight(root, f"sqlite:///{tmp_path / 'ambiguous.db'}")


def test_role_alignment_migration_is_exact_scoped_and_idempotent(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite:///{tmp_path / 'role-alignment.db'}"
    cfg = migration_config(root, database_url)
    command.upgrade(cfg, "202608120018")
    engine = sa.create_engine(database_url, future=True)
    canonical_company = str(uuid.uuid4())
    custom_company = str(uuid.uuid4())
    role_ids = {
        name: str(uuid.uuid4())
        for name in ("manager", "vendor", "custom_manager", "custom_vendor")
    }
    custom_permission = str(uuid.uuid4())
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO companies (id, name, slug, status) VALUES "
                "(:canonical, 'Canonical', 'canonical', 'active'), "
                "(:custom, 'Custom', 'custom', 'active')"
            ),
            {"canonical": canonical_company, "custom": custom_company},
        )
        connection.execute(
            sa.text(
                "INSERT INTO permissions (id, key, description) "
                "VALUES (:id, 'custom.permission', 'Custom permission')"
            ),
            {"id": custom_permission},
        )
        connection.execute(
            sa.text(
                "INSERT INTO roles (id, company_id, name, description) VALUES "
                "(:manager, :canonical, 'Manager', 'Default manager role for operations.'), "
                "(:vendor, :canonical, 'Vendor', "
                "'Default vendor role with canonical portal permissions.'), "
                "(:custom_manager, :custom, 'Manager', 'Custom'), "
                "(:custom_vendor, :custom, 'Vendor', 'Custom')"
            ),
            {**role_ids, "canonical": canonical_company, "custom": custom_company},
        )
        connection.execute(
            sa.text(
                "INSERT INTO role_permissions (role_id, permission_id) VALUES "
                "(:manager, :permission), (:custom_manager, :permission), "
                "(:custom_vendor, :permission)"
            ),
            {**role_ids, "permission": custom_permission},
        )

    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")
    with engine.connect() as connection:
        role_permissions = {
            role_id: set(
                connection.execute(
                    sa.text(
                        "SELECT p.key FROM role_permissions rp "
                        "JOIN permissions p ON p.id = rp.permission_id "
                        "WHERE rp.role_id = :role_id"
                    ),
                    {"role_id": role_id},
                ).scalars()
            )
            for role_id in role_ids.values()
        }
    engine.dispose()

    assert role_permissions[role_ids["manager"]] == set(MANAGER_CORE_PERMISSIONS)
    assert role_permissions[role_ids["custom_manager"]] == {"custom.permission"}
    assert "vendor.ledger.view" in role_permissions[role_ids["vendor"]]
    assert role_permissions[role_ids["custom_vendor"]] == {"custom.permission"}


def test_fresh_installation_matches_runtime_schema_on_postgresql(
    disposable_postgres_url: str,
) -> None:
    root = Path(__file__).resolve().parents[1]
    cfg = migration_config(root, disposable_postgres_url)
    command.upgrade(cfg, "head")
    engine = sa.create_engine(disposable_postgres_url, future=True)
    try:
        assert_head_schema(engine)
    finally:
        engine.dispose()


def test_auth_vendor_migration_roundtrip_preserves_postgresql_data(
    disposable_postgres_url: str,
) -> None:
    root = Path(__file__).resolve().parents[1]
    run_roundtrip(root, disposable_postgres_url)


def test_auth_vendor_migration_rejects_ambiguous_postgresql_links(
    disposable_postgres_url: str,
) -> None:
    root = Path(__file__).resolve().parents[1]
    run_ambiguous_preflight(root, disposable_postgres_url)
