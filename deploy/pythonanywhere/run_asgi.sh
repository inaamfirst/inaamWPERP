#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${ERP_PROJECT_DIR:-/home/YOURUSERNAME/enterprise-commerce-erp}"
VENV_DIR="${ERP_VENV_DIR:-/home/YOURUSERNAME/.virtualenvs/enterprise-commerce-erp}"

cd "$PROJECT_DIR"

ERP_PREFLIGHT_ONLY=1 ERP_PREFLIGHT_SKIP_WORKER_HEARTBEAT=1 \
  "$VENV_DIR/bin/python" -m erp.apps.api

exec "$VENV_DIR/bin/uvicorn" \
  --app-dir "$PROJECT_DIR" \
  --uds "${DOMAIN_SOCKET}" \
  erp.apps.api.main:app
