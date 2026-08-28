# Enterprise Commerce ERP

Production foundation for a modular Python ERP with a PySide6 desktop control center,
FastAPI backend, PostgreSQL primary database, SQLite offline cache, and future
WooCommerce/WhatsApp integrations.

This repository contains the production-ready V1 sellable foundation. It is not
the full ERP product yet; advanced accounting, fulfillment, marketplace,
live automation workflows are intentionally deferred.

- Core multi-tenant architecture with robust tenant isolation and detailed audit logging.
- Identity system featuring bearer session login/logout and PBKDF2 password hashing.
- Catalog management (categories, brands, products, variants, images) and Customers management.
- Inventory ledger system with warehouses and derived stock movement tracking.
- Orders management featuring workflow status transitions and partial/full payment tracking.
- PySide6 Desktop client with an API-backed dashboard and CRUD/list views for business screens.
- WooCommerce connector config storage, mocked connection testing, sync
  mappings, webhook logging, desktop setup screen, and a tested foundation sync loop.
- WhatsApp automation boundary with notification queueing and delivery logs.
- Reports & Dashboard API for sales summaries, stock report listings, and CSV order exporting.
- SQLite/dev backup API, non-destructive restore-plan API, and license
  activation/status APIs.
- Tenant/company administration APIs and desktop Admin screen foundation for
  companies, users, roles, license state, and support diagnostics.
- Lightweight license server shell plus ERP activation, validation, revocation,
  and signed offline grace license support.
- Inno Setup installer definition and build guard for Windows release packaging.

## Quick Start

Two ready folders are available:

- `RUN_ON_PC_OFFLINE`: double-click setup/run files for local Windows testing.
- `UPLOAD_TO_PYTHONANYWHERE`: upload ZIP builder and PythonAnywhere scripts.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
.\scripts\check.ps1
```

The default `.env` configuration uses PostgreSQL at
`postgresql+psycopg://erp:erp@localhost:5432/enterprise_commerce_erp`. Create that
database and user (or edit `ERP_DATABASE_URL` with your PostgreSQL credentials),
then apply the schema:

```powershell
psql -U postgres -c "CREATE USER erp WITH PASSWORD 'erp';"
createdb -U postgres -O erp enterprise_commerce_erp
.\scripts\migrate.ps1
```

SQLite remains available only for the offline PC profile, local cache, and test
smoke runs.

If Windows resolves `python` through Python Manager or another launcher, set
`ERP_PYTHON` to the intended interpreter before running scripts:

```powershell
$env:ERP_PYTHON="C:\Users\User\AppData\Local\Programs\Python\Python311\python.exe"
```

Run the API:

```powershell
.\scripts\run_api.ps1
```

Run the desktop shell:

```powershell
.\scripts\run_desktop.ps1
```

Run the local PC stack:

```powershell
.\scripts\run_pc_local.ps1
```

Or double-click `RUN_ERP.bat` in the repo root. It defaults to the local stack and also accepts
`lan`, `api`, `desktop`, `stop`, `tests`, `check`, and `migrate` as arguments.
The local stack starts the API, desktop, and persistent WooCommerce worker by
default. Set `ERP_START_WORKER=0` only when you deliberately need to run the
desktop/API without background sync processing.

For same-Wi-Fi access from other devices, run `RUN_ERP_LAN.bat` or
`RUN_ERP.bat lan`. That starts the API bound to all interfaces while keeping
the desktop app pointed at `127.0.0.1` on the local PC.

If you want the launcher to advertise a specific LAN address instead of
auto-detecting the current DHCP lease, set `ERP_LAN_IP` before starting the LAN
mode. That is only an override for the displayed URL and dev-server origin
allowlist; it does not replace a real static IP or router DHCP reservation.

To connect the desktop to a hosted API instead of a local API, set:

```powershell
ERP_API_BASE_URL=https://YOURDOMAIN
```

Run the lightweight license API service for development/operator testing:

```powershell
.\scripts\run_license_server.ps1
```

Run database migrations against the configured database:

```powershell
.\scripts\migrate.ps1
```

Build a Windows one-folder package after the quality gate passes:

```powershell
.\scripts\build_package.ps1
.\scripts\smoke_package.ps1
.\scripts\build_installer.ps1
```

Create a SQLite/dev backup through a running local API:

```powershell
.\scripts\backup_sqlite.ps1 -Token "<bearer-token>"
```

Use PostgreSQL in production. The V1 automated backup API is intentionally
limited to SQLite/dev databases; production operators should use the `pg_dump`
and `pg_restore` scripts/runbook.

Production deployment and PostgreSQL backup/restore runbooks:

- `docs/production_deployment.md`
- `docs/pc_and_cloud_deployment.md`
- `docs/postgresql_backup_restore.md`
- `docs/production_monitoring_runbook.md`

PythonAnywhere templates:

- `deploy/pythonanywhere/README.md`

WooCommerce setup:

- `docs/woocommerce_sync_setup.md`

## Commercial Product Rules

- Do not commit secrets, runtime databases, WhatsApp auth caches, release builds, or
  old project files.
- Keep business modules behind explicit module manifests.
- Keep the desktop app talking to the FastAPI API, not directly to PostgreSQL.
- Use PostgreSQL for production and SQLite only for local offline cache and test smoke runs.
