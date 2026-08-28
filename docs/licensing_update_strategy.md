# Licensing and Update Strategy

Licensing is a commercial product concern and must be designed before release
packaging.

## Licensing Direction

- Use one licensed installation/server identity per business deployment.
- Store license state in `licenses`.
- Support online activation first.
- Add offline license files later for customers with unreliable internet.
- Enforce license checks centrally in the backend, not only in the desktop UI.

## Current Commercial Foundation

- `erp-license-server` provides a lightweight license API contract for
  activation, validation, renewal, and revocation.
- `POST /api/v1/licensing/activate` activates through
  `ERP_LICENSE_SERVER_URL` when configured, or through the local
  server-compatible development path when not configured.
- `GET /api/v1/licensing/status` returns tenant-scoped status.
- `POST /api/v1/licensing/validate` returns active, grace, expired, inactive,
  or revoked state centrally from the ERP backend.
- `POST /api/v1/licensing/revoke` revokes a tenant license and records an audit
  event.
- Raw license keys are never stored; the key is HMAC-hashed with
  `ERP_SECRET_KEY`.
- Activations write a signed offline grace license file. The file stores only a
  signed payload envelope, not the raw license key.
- The in-repo license server currently uses an in-memory store for deterministic
  tests. Production hosting must replace this with durable storage, TLS,
  operator authentication, monitoring, backup, and key rotation.

## Update Direction

- Use PyInstaller one-folder builds as the first production packaging baseline.
- Build signed Windows installers with `scripts/build_installer.ps1` and Inno
  Setup after the PyInstaller package smoke passes.
- Keep migrations backward compatible where practical.
- Run database backup before production migrations.
- Record application version, module versions, and migration version during
  support diagnostics.

## Current Packaging Foundation

- `deploy/pyinstaller` contains specs for API, worker, and desktop.
- `scripts/build_package.ps1` runs the quality gate and builds one-folder
  packages.
- `scripts/smoke_package.ps1` verifies expected packaged artifacts.
- `deploy/windows` contains production environment and launcher templates.
- `deploy/inno` contains the customer installer definition and code-signing hook
  documentation.

Remaining production licensing work is cloud operations: persistent license
storage, admin UI for the license service, customer portal integration, payment
provider integration, and formal support override policy.
