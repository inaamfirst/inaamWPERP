# Roadmap

## Phase 1: Production Foundation

- Repository scaffold.
- Architecture docs.
- Module manifests.
- FastAPI shell.
- PySide6 shell.
- Worker placeholder.
- Alembic foundation migration.
- Tests, local scripts, and CI.

## V1.1: Identity Foundation

- First-use setup.
- Company administrator creation.
- PBKDF2 password hashing.
- Bearer session login/logout.
- Permission-backed role, settings, and audit endpoints.

## V1.2: Catalog And Customers Foundation

- Tenant-scoped categories, brands, products, variants, and images.
- Tenant-scoped customers, addresses, notes, and tags.
- FastAPI CRUD endpoints with RBAC and audit logging.
- Migration smoke tests and API tests for validation, auth, and tenant
  isolation.

## V1.3: Inventory Foundation

- Tenant-scoped warehouses.
- Stock movement ledger for opening stock, stock in, stock out, damaged stock,
  and adjustments.
- Derived stock balance API grouped by warehouse, product, and variant.
- Negative-stock protection, RBAC, audit logging, and tenant-isolation tests.

## V1.4: Orders Foundation

- Tenant-scoped orders, order items, status history, and payments.
- Status transition rules for pending through refunded lifecycle.
- Product/customer references with item snapshots for historic integrity.
- Payment recording with partial/paid order payment states.
- Inventory deduction intentionally deferred to a fulfillment policy phase.

## V1.5: Desktop Business Screens

- Navigation for Dashboard, Products, Customers, Inventory, Orders, and
  Settings.
- API-backed product and customer create/list screens.
- API-backed read-only inventory and order list screens.
- Offline/API-unavailable states shown without crashing.

## V1.6: WooCommerce Connector Foundation

- Encrypted WooCommerce site URL, consumer key, and consumer secret storage.
- Safe config read API that never returns secrets.
- Mocked connection test endpoint.
- External id mapping helpers for products, customers, and orders.
- Idempotent `sync_outbox` enqueue helper.
- Foundation sync loop for products, customers, orders, webhook intake, sync
  run logs, and conflict resolution.
- Rich conflict UI, ownership policy tuning, rate-limit handling, and full
  production connector hardening remain deferred.

## V1.7: WhatsApp Connector Foundation

- Notification templates.
- WhatsApp message queue.
- Delivery log foundation.
- Mock-local adapter for tests and development.
- Adapter boundary documented for the existing Windows WhatsApp automation.
- Real WhatsApp automation intentionally deferred until explicitly approved.

## V1.8: Reports And Dashboard Foundation

- Dashboard summary API for sales count, revenue, pending orders, low-stock
  count, customer count, and product count.
- Sales, inventory, customer, and order report endpoints.
- Orders CSV export.
- Desktop dashboard consumes the dashboard-summary API.
- Low stock is currently defined as active products with derived stock at or
  below zero; reorder thresholds are deferred.

## V1.9: Backup, Restore, And Licensing Foundation

- SQLite/dev backup API.
- Non-destructive restore-plan API.
- Tenant-scoped license activation/status API.
- Raw license keys are not stored.
- Production PostgreSQL backup automation remains operator-run through
  documented scripts.

## V1.10: Hardening And Readiness

- Security, tenant-isolation, error-handling, and documentation pass.
- `.env.example` coverage test.
- Local `scripts/check.ps1` quality gate with lint, tests, API smoke, and
  Alembic SQLite migration smoke.
- V1 readiness report.

## V1.11: Packaging And Production Operations Foundation

- PyInstaller one-folder specs for API, worker, and desktop.
- Package build and artifact smoke scripts.
- Windows production environment and launcher templates.
- PostgreSQL backup and restore scripts with explicit restore confirmation.
- Production deployment and PostgreSQL backup/restore runbooks.

## V1.12: V3 Expansion Planning

- Decision-ready V3 plan for vendors/marketplace, accounting, delivery/COD,
  mobile API, AI assistant, and plugin marketplace.
- No V3 implementation is approved in this phase.

## V1.13: Commercial Release Foundation

- Tenant/company administration APIs and desktop Admin screen foundation.
- User and role administration APIs with password reset support.
- Lightweight license server service shell.
- ERP license activation, validation, revocation, and signed offline grace file.
- Redacted support diagnostics summary and ZIP export.
- Inno Setup installer definition and build guard.
- Production monitoring, migration safety, worker diagnosis, license support,
  and diagnostics runbook.

## V1: Remaining Before Sellable Beta

- Persistent cloud license service storage and operator UI.
- Code signing and formal update delivery.
- Seed/demo data policy.
- Live WooCommerce certification for the first retail beta customer.

## V2: Commerce Hardening

- Full WooCommerce two-way sync.
- Webhook logs and conflict UI.
- Purchases and suppliers.
- Stock transfers.
- Barcode workflows.
- Stronger reports.
- Update flow.

## V3: Expansion

- Vendors and marketplace support.
- Accounting.
- Delivery and COD collection.
- Mobile API/app.
- AI assistant.
- Plugin marketplace.
