# Upload To PythonAnywhere

Use this folder when deploying the ERP backend/API to PythonAnywhere.

The Windows desktop app does not run inside PythonAnywhere. PythonAnywhere hosts
the FastAPI API and PostgreSQL database. The PC desktop connects to it by
setting:

```env
ERP_API_BASE_URL=https://YOURUSERNAME.pythonanywhere.com
```

## Create Upload ZIP

Double-click:

```text
CREATE_PYTHONANYWHERE_UPLOAD_ZIP.bat
```

It creates:

```text
build_output\enterprise-commerce-erp-pythonanywhere.zip
```

Upload that ZIP to PythonAnywhere and extract it under:

```text
/home/YOURUSERNAME/enterprise-commerce-erp
```

## PythonAnywhere Setup

On PythonAnywhere Bash console:

```bash
cd /home/YOURUSERNAME/enterprise-commerce-erp
mkvirtualenv enterprise-commerce-erp --python=python3.11
pip install --upgrade pip
pip install -e ".[dev]"
cp UPLOAD_TO_PYTHONANYWHERE/pythonanywhere.env.example .env
```

Edit `.env` and replace every `CHANGE_ME` and `YOURUSERNAME`.

Run migrations:

```bash
bash UPLOAD_TO_PYTHONANYWHERE/migrate.sh
```

Create ASGI website:

```bash
pip install --upgrade pythonanywhere
pa website create --domain YOURUSERNAME.pythonanywhere.com --command '/bin/bash /home/YOURUSERNAME/enterprise-commerce-erp/UPLOAD_TO_PYTHONANYWHERE/run_asgi.sh'
```

Reload after changes:

```bash
pa website reload --domain YOURUSERNAME.pythonanywhere.com
```

If using a paid account with always-on tasks, worker command:

```bash
/bin/bash /home/YOURUSERNAME/enterprise-commerce-erp/UPLOAD_TO_PYTHONANYWHERE/run_worker.sh
```

## Do Not Upload

- `.env`
- `.venv`
- runtime databases
- logs
- WhatsApp auth/cache folders
- certificates or private keys
- old project folders
- customer data
