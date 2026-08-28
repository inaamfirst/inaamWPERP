# Deployment

Deployment assets are intentionally configuration and runbook files only. Build
outputs belong under `release_builds/` and must not be committed.

Included:

- `pyinstaller/`: one-folder PyInstaller specs for API, worker, and desktop.
- `inno/`: Inno Setup customer installer definition and signing hook notes.
- `pythonanywhere/`: FastAPI ASGI, PostgreSQL, migration, and worker templates
  for PythonAnywhere cloud API deployments.
- `windows/`: production environment template and packaged launch scripts.

Primary docs:

- `docs/production_deployment.md`
- `docs/pc_and_cloud_deployment.md`
- `docs/postgresql_backup_restore.md`
- `docs/production_monitoring_runbook.md`
- `docs/authentication_vendor_ledger.md`

Installer output, release packages, signing material, customer databases, logs,
and runtime folders must never be committed.

Future release operations still need Windows service registration, update
channels, and customer-specific deployment automation.
