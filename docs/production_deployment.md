# Production Deployment

This is the supported Windows production deployment for ChoiceOye's operational
ERP release: catalog, inventory, orders, desktop API, worker, and WooCommerce
media sync. It is deliberately not a claim that every module is a finished
commercial SaaS service. Marketplace, accounting, licensing, and customer
messaging are visibly marked foundation-only until each has its own production
approval.

## Production profile

Production startup is intentionally strict. It refuses to start with SQLite,
default secrets, an HTTP/non-public API URL, wildcard trusted hosts, disabled
HTTPS enforcement, or a disabled worker. A successful preflight also requires:

- PostgreSQL and an Alembic revision matching the package head;
- `pg_dump` available to the API/worker service account;
- writable media, log, diagnostics, and backup locations;
- a protected environment file (or managed environment variables); and
- a fresh worker heartbeat after the worker is running.

Do not point a production desktop at a development SQLite database. SQLite is
kept only for local development/cache and isolated package smoke checks.

## Build and release verification

From the controlled release checkout:

```powershell
.\scripts\build_package.ps1
.\scripts\build_installer.ps1
```

`build_package.ps1` runs the quality gate unless `-SkipChecks` is supplied. It
then runs `smoke_package.ps1`, which creates an isolated temporary SQLite
database, applies migrations, starts the packaged API, runs the packaged worker,
and runs the packaged desktop in a non-GUI smoke mode. It never uses a
production database or configuration.

`-SkipPackageSmoke` is for a local package-debugging investigation only; do not
use it for a release candidate. The installer build also reruns the package
smoke unless explicitly skipped.

Sign the installer and executables only in secure release infrastructure. Do
not put code-signing certificates, `.env` files, databases, logs, backups, or
customer media in `release_builds`.

## Install and configure

1. Install the signed Inno Setup package as an administrator. It installs the
   executables under `Program Files` and places a template at:

   ```text
   C:\ProgramData\ChoiceOye\Enterprise Commerce ERP\production.env.example
   ```

2. Copy the template to `production.env`, replace every placeholder, and
   restrict its ACL to `SYSTEM` and the designated deployment administrator.
   The managed API/worker tasks run as `LocalSystem`, so it needs read access.

   ```powershell
   $dataRoot = 'C:\ProgramData\ChoiceOye\Enterprise Commerce ERP'
   Copy-Item "$dataRoot\production.env.example" "$dataRoot\production.env"
   icacls "$dataRoot\production.env" /inheritance:r
   icacls "$dataRoot\production.env" /grant:r "SYSTEM:(R)" "Administrators:(F)"
   ```

   Do not leave `Everyone`, `BUILTIN\Users`, or `Authenticated Users` with
   access. Do not store the real configuration inside the application folder or
   in source control.

3. Configure the required fields in `production.env`:

   - `ERP_ENV=production`
   - a PostgreSQL `ERP_DATABASE_URL` with non-development credentials
   - long random `ERP_SECRET_KEY`, `ERP_LICENSE_SERVER_ADMIN_KEY`, and
     `ERP_LICENSE_OFFLINE_SIGNING_KEY`
   - public HTTPS `ERP_API_BASE_URL`
   - explicit `ERP_TRUSTED_HOSTS` and the loopback/reverse-proxy-only
     `ERP_TRUSTED_PROXY_IPS`
   - `ERP_FORCE_HTTPS=true`, `ERP_WORKER_LOOP=true`, and paths under
     `C:\ProgramData\ChoiceOye\Enterprise Commerce ERP`
   - `ERP_MAX_REQUEST_SIZE_MB=10` (a positive integer; raise it only for
     approved upload requirements)

4. Put TLS and the public hostname in a reverse proxy. Bind the packaged API to
   loopback only. The task installer checks the configured public HTTPS health
   URL; a local `http://127.0.0.1` readiness URL is not a production substitute.

5. Install PostgreSQL client tools for the service account and verify `pg_dump`
   is on its `PATH`.

## Migration and managed services

Set the installed application/configuration locations once, then back up
PostgreSQL before every migration or package upgrade:

```powershell
$root = 'C:\Program Files\ChoiceOye\Enterprise Commerce ERP'
$config = 'C:\ProgramData\ChoiceOye\Enterprise Commerce ERP\production.env'
& "$root\backup_postgres.ps1" `
  -Database enterprise_commerce_erp `
  -Username erp_app_user `
  -HostName 127.0.0.1 `
  -Port 5432 `
  -OutputDir 'C:\ProgramData\ChoiceOye\Enterprise Commerce ERP\backups'
```

Apply the bundled Alembic release migration with the same protected
configuration, then verify the current revision before starting managed
services:

```powershell
$root = 'C:\Program Files\ChoiceOye\Enterprise Commerce ERP'
$config = 'C:\ProgramData\ChoiceOye\Enterprise Commerce ERP\production.env'
& "$root\migrate_database.ps1" -AppRoot $root -ConfigFile $config
```

The installer intentionally does not start the API automatically: configuration,
migrations, the reverse proxy, and backup verification must all be completed
first. Once they are, run the packaged managed-task installer from an elevated
PowerShell session:

```powershell
& "$root\install_managed_tasks.ps1" -AppRoot $root -ConfigFile $config
```

This registers `ChoiceOye ERP API` and `ChoiceOye ERP Worker` as restartable
LocalSystem startup tasks, starts them, waits for the public HTTPS health
endpoint, and completes the full preflight including the worker heartbeat.

For a configuration-only validation before the worker is started, use:

```powershell
& "$root\preflight_production.ps1" -AppRoot $root -ConfigFile $config -SkipWorkerHeartbeat
```

To remove the managed tasks during an intentional uninstall:

```powershell
& "$root\uninstall_managed_tasks.ps1"
```

## Operational checks

- Confirm `https://YOUR_HOST/api/v1/health` reports `healthy` and the expected
  migration revision.
- Open the desktop and verify API health plus the diagnostics summary.
- Confirm `runtime_data\worker_heartbeat.json` updates at least every three
  poll intervals.
- Trigger only read-only live WooCommerce checks during release verification
  unless a designated staging product is approved.
- Keep normal WooCommerce product payloads media-free. ERP media is additive:
  remote website images stay intact unless an ERP image is explicitly marked
  `pending_remove`.

Use [the monitoring runbook](production_monitoring_runbook.md) for request ID,
worker, sync, backup, and incident procedures. PythonAnywhere deployment
instructions remain in `deploy/pythonanywhere`; the Windows desktop still runs
on an operator PC in that model.
