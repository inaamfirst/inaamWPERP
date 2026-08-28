# PostgreSQL Backup And Restore

PostgreSQL is the production database. SQLite backup APIs are for development
and local smoke use only.

## Backup

Install PostgreSQL client tools and ensure `pg_dump` is on `PATH`.

Use `PGPASSWORD`, `.pgpass`, or an operator prompt for authentication. Do not
place database passwords in command history or scripts.

```powershell
.\scripts\backup_postgres.ps1 `
  -Database enterprise_commerce_erp `
  -Username erp_app_user `
  -HostName 127.0.0.1 `
  -Port 5432
```

The script creates a custom-format dump under
`runtime_data/postgres_backups/`. That directory is ignored by git.

## Restore

Restore is destructive. Verify the backup file, target database, and downtime
window before running it.

```powershell
.\scripts\restore_postgres.ps1 `
  -BackupFile runtime_data\postgres_backups\enterprise_commerce_erp-YYYYMMDD-HHMMSS.dump `
  -Database enterprise_commerce_erp `
  -Username erp_app_user `
  -HostName 127.0.0.1 `
  -Port 5432 `
  -ConfirmRestore
```

The restore script refuses to run unless `-ConfirmRestore` is present.

## Operational Policy

- Back up before production migrations and package upgrades.
- Keep at least one tested restore procedure per customer deployment.
- Store backups in an encrypted location outside the application folder.
- Test restore on a non-production database before relying on a backup.
- Never commit dumps, SQLite databases, logs, or `.env` files.
