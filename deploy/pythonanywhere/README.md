# PythonAnywhere Deployment

PythonAnywhere can host the FastAPI backend as an ASGI site. The Windows
PySide6 desktop app does not run inside PythonAnywhere; it runs on the PC and
connects to the cloud API through `ERP_API_BASE_URL`.

## Recommended Mode

- Cloud: FastAPI API, PostgreSQL database, migrations, optional worker.
- PC: PySide6 desktop client configured with
  `ERP_API_BASE_URL=https://YOURUSERNAME.pythonanywhere.com`.

## Important Limitations

- PythonAnywhere ASGI support is currently documented as experimental/beta.
- Always-on worker tasks require a paid PythonAnywhere account.
- The desktop UI is not a browser UI. A true cloud-only browser experience
  requires a future web frontend.
- Do not upload `.env`, runtime databases, logs, WhatsApp auth caches, signing
  keys, or old project folders.

## Setup Outline

1. Upload or clone this repository to PythonAnywhere, for example:
   `/home/YOURUSERNAME/enterprise-commerce-erp`.
2. Create a virtualenv and install the package:

   ```bash
   mkvirtualenv enterprise-commerce-erp --python=python3.11
   cd /home/YOURUSERNAME/enterprise-commerce-erp
   pip install --upgrade pip
   pip install -e ".[dev]"
   ```

3. Copy `env.production.example` to `.env` in the repository root on
   PythonAnywhere and replace all placeholders with real values. The ERP loads
   this file from the project root; the shell scripts do not source it.
4. Create PostgreSQL database/user from the PythonAnywhere Databases tab.
5. Run migrations:

   ```bash
   bash deploy/pythonanywhere/migrate.sh
   ```

6. Install the PythonAnywhere command-line tool:

   ```bash
   pip install --upgrade pythonanywhere
   ```

7. Create the ASGI website using the command in `asgi_command.txt`:

   ```bash
   pa website create --domain YOURUSERNAME.pythonanywhere.com --command '/bin/bash /home/YOURUSERNAME/enterprise-commerce-erp/deploy/pythonanywhere/run_asgi.sh'
   ```

   After code or environment changes:

   ```bash
   pa website reload --domain YOURUSERNAME.pythonanywhere.com
   ```

8. Visit `/api/v1/health` and `/docs`.
9. On the PC, set `ERP_API_BASE_URL` in the desktop `.env` to the cloud URL.

## Worker

If the deployment needs scheduled sync/background work, create a paid
PythonAnywhere Always-on task using the command in `run_worker.sh`.

Task command:

```bash
/bin/bash /home/YOURUSERNAME/enterprise-commerce-erp/deploy/pythonanywhere/run_worker.sh
```

Do not run destructive restore operations automatically on PythonAnywhere.
