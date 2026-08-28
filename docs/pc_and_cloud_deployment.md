# PC And Cloud Deployment

The product supports two deployment modes now:

1. Local PC mode: API and desktop run on the Windows PC, with the worker optional.
2. Cloud API mode: FastAPI and PostgreSQL run on a server, while the Windows
   desktop runs on the PC and connects to the cloud API.

The current PySide6 desktop is not a browser app. A true cloud-only browser ERP
needs a future web frontend. PythonAnywhere can host the API, but it will not
run the Windows desktop UI inside the browser.

## Local PC Mode

Use this when the shop runs the ERP on one Windows machine.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
.\scripts\migrate.ps1
.\scripts\run_pc_local.ps1
```

`run_pc_local.ps1` starts the API and a persistent background worker in hidden
PowerShell processes, then opens the desktop app. Set `ERP_START_WORKER=0` only
when the background worker must be disabled deliberately.

## Cloud API Mode

Use this when the shop wants the database/API online, but still uses the Windows
desktop as the control center.

Server:

- host FastAPI on PythonAnywhere or another server
- use PostgreSQL
- run Alembic migrations
- keep worker/sync jobs in an always-on task or equivalent process manager

PC:

- install the desktop app
- set `ERP_API_BASE_URL=https://YOURDOMAIN`
- run `scripts/run_desktop.ps1`

When `ERP_API_BASE_URL` is set, the desktop ignores the local `ERP_API_HOST` and
`ERP_API_PORT` for API calls.

## PythonAnywhere Notes

PythonAnywhere supports FastAPI through its ASGI beta command-line flow. Their
documented command pattern uses Uvicorn with `--uds ${DOMAIN_SOCKET}`. The
templates under `deploy/pythonanywhere` follow that model.

PostgreSQL on PythonAnywhere requires a paid account. Always-on worker tasks
also require a paid account.

Use these templates:

- `deploy/pythonanywhere/env.production.example`
- `deploy/pythonanywhere/asgi_command.txt`
- `deploy/pythonanywhere/run_asgi.sh`
- `deploy/pythonanywhere/migrate.sh`
- `deploy/pythonanywhere/run_worker.sh`

## Not Yet Cloud-Only

For cloud-only browser use, the missing piece is a web frontend. The current API
is ready to serve one later, but the existing UI is Windows/PySide6.
