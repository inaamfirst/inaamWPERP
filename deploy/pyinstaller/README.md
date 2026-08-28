# PyInstaller Packaging

These specs package the current executable surfaces:

- `erp-api`
- `erp-worker`
- `erp-desktop`

Builds are intentionally one-folder packages first. One-folder builds are easier
to inspect, sign, and smoke test before moving to a full installer.

Run from the repository root:

```powershell
.\scripts\build_package.ps1
```

The script runs `scripts/check.ps1` before packaging unless `-SkipChecks` is
passed. Generated artifacts go to `release_builds/` and remain ignored by git.

Do not package `.env`, runtime databases, logs, WhatsApp auth caches, old
project folders, or customer data.
