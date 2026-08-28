# Production Monitoring Runbook

This runbook covers the supported ChoiceOye operational ERP release: catalog,
inventory, orders, desktop API, worker, and WooCommerce/media sync. It does not
promote foundation-only marketplace, accounting, licensing, or customer
messaging features to independently approved production services.

## Startup and release checks

1. Confirm the protected production configuration is at
   `C:\ProgramData\ChoiceOye\Enterprise Commerce ERP\production.env` and uses
   PostgreSQL, non-default secrets, a public HTTPS API URL, explicit trusted
   hosts, and `ERP_WORKER_LOOP=true`.
2. Confirm PostgreSQL has a verified fresh backup and `pg_dump` is available to
   the LocalSystem service account.
3. Apply migrations with the packaged `migrate_database.ps1` launcher using
   that same protected configuration.
4. Confirm the `ChoiceOye ERP API` and `ChoiceOye ERP Worker` Scheduled Tasks
   are `Ready`/running and have no repeated restart failures.
5. Run the packaged `preflight_production.ps1` without
   `-SkipWorkerHeartbeat`. It must report all required checks as successful.
6. Request the public `https://YOUR_HOST/api/v1/health`, then open the desktop
   and confirm its diagnostics summary loads.

The preflight is deliberately safe: it tests connectivity, migration revision,
storage, config ACLs, backup-tool presence, and the heartbeat. It does not
change WooCommerce data.

## Logs, request IDs, and diagnostics

- API and worker logs rotate in the configured `ERP_LOG_DIR` as `erp.jsonl`.
  Each record contains the timestamp, level, operation, request ID, and (where
  applicable) sync run/worker IDs.
- Every API response carries `X-Request-ID`. Safe API errors also include the
  request ID and operation. Capture both when reporting a desktop “Internal
  Server Error”; do not treat that as an offline API unless the health request
  also fails.
- Use `GET /api/v1/support/diagnostics` or
  `GET /api/v1/support/diagnostics.zip` for a redacted support snapshot. It
  includes migration/module/runtime health but excludes `.env`, database files,
  logs, customer documents, certificates, and keys.

## Worker and sync diagnosis

1. Check public API health and the current migration revision first.
2. Check
   `C:\ProgramData\ChoiceOye\Enterprise Commerce ERP\runtime_data\worker_heartbeat.json`.
   It should identify the worker, state, run ID if any, and a recent timestamp.
3. Inspect the latest `sync_run_logs` state through the WooCommerce page or
   diagnostics: queued/running/success/failed, lease/attempt count, `Media Out`,
   pending media, deferred media, and media failures.
4. Inspect the WooCommerce outbox and open conflicts. A stale lease or pending
   outbox is recovered by the worker; do not manually delete rows to “fix” it.
5. For a failed remote call, use the run ID, request ID, and `erp.jsonl` entry.
   Retry only after correcting credentials, network/DNS, remote rate limit, or
   remote timeout. The worker uses retryable states/backoff for temporary
   remote failures.

Normal product sync is non-destructive for website media: product payloads do
not carry `images`; local ERP uploads are attached additively; existing website
gallery/media remains until an ERP image is explicitly `pending_remove`. A media
failure must leave the remote gallery intact.

## Backup and migration incident handling

1. Stop data-entry operations before an emergency restore.
2. Verify the backup file, intended PostgreSQL database, and maintenance
   window.
3. Use `scripts/restore_postgres.ps1` only with its explicit
   `-ConfirmRestore` flag.
4. After restore, apply the intended migration revision, restart the managed
   tasks, run full preflight, and verify public health before reopening the
   desktop.

Never run destructive cleanup, database restore, or WooCommerce media deletion
as an automated recovery action.

## License support boundary

The repository's license service is an API contract/testable service shell.
Before licensing is sold at scale, its hosting separately needs durable storage,
operator authentication, TLS, backups, monitoring, and key rotation. Do not use
license support procedures as evidence that the licensing module is a complete
commercial SaaS service.