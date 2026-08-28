#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${ERP_PROJECT_DIR:-/home/YOURUSERNAME/enterprise-commerce-erp}"
VENV_DIR="${ERP_VENV_DIR:-/home/YOURUSERNAME/.virtualenvs/enterprise-commerce-erp}"

cd "$PROJECT_DIR"

"$VENV_DIR/bin/python" -m alembic -c alembic.ini upgrade head
