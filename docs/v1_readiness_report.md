# V1 Readiness Report

## Complete In This Foundation

- Repository scaffold with FastAPI, PySide6, worker, Alembic, tests, scripts,
  and Windows CI.
- Tenant-scoped identity, settings, audit, catalog, customers, inventory,
  orders, reports, WooCommerce foundation, WhatsApp notification foundation,
  backup foundation, and licensing foundation.
- RBAC-protected API endpoints for implemented modules.
- Alembic migrations for platform and V1 business foundation tables.
- Desktop shell with API status, login, dashboard summary, product/customer
  create/list screens, read-only inventory/order screens, and settings view.
- Local mock WooCommerce sync/webhook/outbox/conflict foundations with tests.
- Mock WhatsApp queue/template/delivery foundation with tests.
- SQLite/dev backup API and non-destructive restore-plan API with tests.
- Production-style license activation/status/validation/revocation foundation,
  lightweight license server shell, signed offline grace file, and no raw
  license key persistence.
- Tenant/company administration APIs and desktop Admin screen foundation for
  companies, users, roles, password resets, license state, and diagnostics.
- Support diagnostics API and redacted diagnostic ZIP export.
- Local quality gate: `scripts/check.ps1`.
- PyInstaller one-folder packaging specs for API, worker, and desktop.
- Inno Setup installer definition, installer build guard, production deployment
  templates, and PostgreSQL backup/restore runbooks.

## Partial Or Foundation Only

- WooCommerce sync is tested against mocks, not a live customer store.
- WhatsApp integration uses a mock adapter only; the existing Windows
  automation app is not controlled by this repo yet.
- Backup API automation is SQLite/dev only. PostgreSQL production backup uses
  operator-run `pg_dump`/`pg_restore` scripts and a runbook.
- The license server shell uses in-memory storage for deterministic local tests.
  Production hosting still needs persistent storage, TLS, operator
  authentication, monitoring, backups, and key rotation.
- Desktop screens cover V1 basics but not rich operational workflows.
- Reports are operational summaries, not accounting-grade reports.

## Deferred Before Commercial Release

- Code signing certificate integration, auto-update delivery, and release
  channel management.
- Stronger company onboarding and platform-admin UX for multi-company support.
- Full WooCommerce ownership rules, conflict UI, rate-limit handling, and live
  store certification.
- Real WhatsApp adapter approval, isolation, observability, and operator safety
  controls.
- Accounting, purchases, suppliers, stock transfers, delivery/COD, marketplace,
  CRM, mobile, and AI modules.

## Current Quality Gate

Before accepting the foundation, run:

```powershell
.\scripts\check.ps1
```

The gate runs Ruff, pytest, FastAPI app creation smoke, Alembic config smoke,
and a real Alembic migration against a temporary SQLite database.
