# Architecture

The ERP uses a Python modular monolith with separate executable surfaces:

- `erp.apps.api`: FastAPI backend and OpenAPI documentation.
- `erp.apps.desktop`: PySide6 Windows desktop shell.
- `erp.apps.worker`: background worker shell for future sync and scheduled jobs.
- `erp.packages.core`: shared configuration, database, module registry, logging,
  and platform services.
- `erp.packages.modules`: module folders with manifests and future module code.

## Runtime Direction

The desktop app talks to the FastAPI API. It must not write directly to
PostgreSQL. This keeps validation, permissions, audit logging, sync, and future
mobile access behind the same backend boundary.

PostgreSQL is the production database. SQLite is used for local offline cache
and test smoke validation.

## Current Surface

- API health endpoint.
- API module manifest endpoint.
- First-use setup endpoint.
- Login, logout, and current-user endpoints.
- Role, permission, settings, and audit-log foundation endpoints.
- Catalog endpoints for categories, brands, products, variants, and images.
- Customer endpoints for customer profiles, addresses, notes, and tags.
- Inventory endpoints for warehouses, stock movements, and derived stock
  balances.
- Order endpoints for order creation, detail/list views, status changes, and
  payments.
- WooCommerce connector endpoints for encrypted credential configuration and
  mocked-testable connection checks, sync execution, sync run logs, webhook
  intake, external id mapping, outbox processing, and conflict resolution.
- WhatsApp connector endpoints for templates, queueing, delivery logs, and
  mock-local delivery simulation.
- Reports endpoints for dashboard summary, sales, inventory, customers, orders,
  and order CSV export.
- Backup endpoints for SQLite/dev backup creation and non-destructive restore
  planning.
- Licensing endpoints for local mock activation and license status.
- Desktop shell with API status, login, dashboard summary counts, product and
  customer create/list screens, plus read-only inventory and order lists.
- Worker shell that runs configured WooCommerce sync jobs or reports idle when
  no connector is configured.
- PyInstaller one-folder packaging specs, Windows launch templates, and
  PostgreSQL backup/restore scripts.
- Alembic migrations for platform, authentication sessions, catalog, customers,
  inventory, orders, and WhatsApp notification tables.

Advanced desktop workflows such as rich dashboards, barcode operations,
connector setup screens, restore execution, and order editing are deferred. Real
WhatsApp sending, signed installer/update delivery, accounting, marketplace,
delivery, and AI modules are also deferred.
