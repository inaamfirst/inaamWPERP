# Inno Setup Installer

This folder contains the signed Windows installer definition for the packaged
ERP desktop, API, worker, managed-task scripts, and production configuration
template.

Build order from the repository root:

```powershell
.\scripts\build_package.ps1
.\scripts\build_installer.ps1
```

`build_package.ps1` includes an isolated temporary integration smoke: packaged
API health, packaged worker heartbeat, and packaged desktop non-GUI mode. The
installer build reruns that smoke before it invokes Inno Setup.

The installer deliberately **does not** auto-start the API. An operator must
first create and protect the production configuration, verify a PostgreSQL
backup, run the bundled `migrate_database.ps1` launcher, configure the public
HTTPS reverse proxy, then run `install_managed_tasks.ps1` from an elevated
PowerShell session. This avoids starting an unconfigured or schema-incompatible
service.

After installation, the production template is located at:

```text
C:\ProgramData\ChoiceOye\Enterprise Commerce ERP\production.env.example
```

Copy it to `production.env`, replace placeholders, and permit only LocalSystem
and the designated deployment administrator to read it. The installer does not
ship a real `.env`.

The installer reads from `release_builds/dist` and writes to
`release_builds/installer`. Those generated folders must not be committed.

Forbidden files must never ship in the installer:

- `.env` or `.env.*`
- runtime databases, logs, and backups
- WhatsApp browser auth/cache folders
- private certificates or signing keys
- copied legacy projects or customer data

Code signing is intentionally a release-workstation or CI concern. Configure
the commented `SignTool` line in `installer.iss` only with a real certificate
available through secure release infrastructure.