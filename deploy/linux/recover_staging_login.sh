#!/usr/bin/env bash
set -Eeuo pipefail

# Safe diagnostics and recovery for the staging administrator. The helper does
# not source staging.env because systemd environment files can contain values
# (for example JSON arrays) that Bash would reinterpret.

APP_ROOT="${APP_ROOT:-/opt/inaam-erp}"
ENV_FILE="${ENV_FILE:-/etc/inaam-erp/staging.env}"
PYTHON_BIN="$APP_ROOT/.venv/bin/python"
MODE="${1:---probe}"

if [[ "$(id -u)" != 0 ]]; then
  echo "Run this helper as root from the DigitalOcean Web Console." >&2
  exit 1
fi
if [[ "$MODE" != "--probe" && "$MODE" != "--reset-password" ]]; then
  echo "Usage: $0 [--probe|--reset-password]" >&2
  exit 1
fi
if [[ ! -x "$PYTHON_BIN" || ! -f "$ENV_FILE" ]]; then
  echo "ERP virtual environment or staging environment file is missing." >&2
  exit 1
fi

read_env_value() {
  local key="$1" value
  value="$(sed -n "s/^${key}=//p" "$ENV_FILE" | head -n 1)"
  if [[ -z "$value" ]]; then
    echo "Missing $key in $ENV_FILE" >&2
    exit 1
  fi
  if [[ "${value:0:1}" == "'" && "${value: -1}" == "'" ]]; then
    value="${value:1:${#value}-2}"
  elif [[ "${value:0:1}" == '"' && "${value: -1}" == '"' ]]; then
    value="${value:1:${#value}-2}"
  fi
  printf '%s' "$value"
}

DATABASE_URL="$(read_env_value ERP_DATABASE_URL)"
API_BASE_URL="$(read_env_value ERP_API_BASE_URL)"

read -r -p "Workspace slug [staging]: " ERP_RECOVERY_WORKSPACE
ERP_RECOVERY_WORKSPACE="${ERP_RECOVERY_WORKSPACE:-staging}"
read -r -p "Administrator username [admin]: " ERP_RECOVERY_USERNAME
ERP_RECOVERY_USERNAME="${ERP_RECOVERY_USERNAME:-admin}"
if [[ "$MODE" == "--reset-password" ]]; then
  read -r -s -p "New password (12+ characters): " ERP_RECOVERY_PASSWORD
else
  read -r -s -p "Current password: " ERP_RECOVERY_PASSWORD
fi
echo

export ERP_RECOVERY_DATABASE_URL="$DATABASE_URL"
export ERP_RECOVERY_API_BASE_URL="$API_BASE_URL"
export ERP_RECOVERY_WORKSPACE ERP_RECOVERY_USERNAME ERP_RECOVERY_PASSWORD ERP_RECOVERY_MODE="$MODE"
trap 'unset ERP_RECOVERY_DATABASE_URL ERP_RECOVERY_API_BASE_URL ERP_RECOVERY_WORKSPACE ERP_RECOVERY_USERNAME ERP_RECOVERY_PASSWORD ERP_RECOVERY_MODE' EXIT

cd "$APP_ROOT"
"$PYTHON_BIN" - <<'PY'
import hashlib
import json
import os
import secrets
import sys
import urllib.error
import urllib.request
from urllib.parse import urlparse

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from erp.packages.core.db.models import Company, LoginThrottle, User


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt, expected = password_hash.split("$", 3)
        iterations = int(iterations_text)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), iterations
    ).hex()
    return secrets.compare_digest(actual, expected)


def password_hash(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000).hex()
    return f"pbkdf2_sha256$260000${salt}${digest}"


def post_json(url: str, payload: dict[str, object], headers: dict[str, str]) -> tuple[int, object]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, response.headers
    except urllib.error.HTTPError as error:
        return error.code, error.headers


database_url = os.environ["ERP_RECOVERY_DATABASE_URL"]
api_base_url = os.environ["ERP_RECOVERY_API_BASE_URL"].rstrip("/")
workspace = os.environ["ERP_RECOVERY_WORKSPACE"]
username = os.environ["ERP_RECOVERY_USERNAME"]
password = os.environ["ERP_RECOVERY_PASSWORD"]
mode = os.environ["ERP_RECOVERY_MODE"]

engine = create_engine(database_url, future=True)
with Session(engine) as db:
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        raise SystemExit(f"Administrator {username!r} was not found.")
    company = db.get(Company, user.company_id)
    if company is None or company.slug != workspace:
        actual = company.slug if company else "missing"
        raise SystemExit(f"Workspace mismatch. Requested {workspace!r}; account uses {actual!r}.")
    if mode == "--reset-password":
        if len(password) < 12:
            raise SystemExit("New password must contain at least 12 characters.")
        user.password_hash = password_hash(password)
        db.execute(delete(LoginThrottle))
        db.commit()
        print("Administrator password reset; login throttles cleared.")
    elif not verify_password(password, user.password_hash):
        raise SystemExit("The supplied password does not match this administrator account.")

parsed = urlparse(api_base_url)
if parsed.scheme != "https" or not parsed.netloc:
    raise SystemExit("ERP_API_BASE_URL must be an HTTPS URL.")
payload = {
    "workspace_slug": workspace,
    "username": username,
    "password": password,
    "supports_refresh": True,
}
direct_status, _ = post_json(
    "http://127.0.0.1:8000/api/v1/auth/login",
    payload,
    {"Host": parsed.netloc, "X-Forwarded-Proto": "https"},
)
print(f"Direct API login: HTTP {direct_status}")
if direct_status != 200:
    raise SystemExit("Direct API login failed; no browser changes were made.")

bff_status, bff_headers = post_json(f"{api_base_url}/api/backend/auth/login", payload, {})
cookie_headers = bff_headers.get_all("Set-Cookie", [])
has_access = any(header.startswith("erp_access=") for header in cookie_headers)
has_csrf = any(header.startswith("erp_bff_csrf=") for header in cookie_headers)
print(f"Browser BFF login: HTTP {bff_status}; auth cookies set: {has_access and has_csrf}")
if bff_status != 200 or not (has_access and has_csrf):
    raise SystemExit("Browser BFF login failed; inspect the frontend service and Nginx configuration.")
print("Login path verified. Clear browser cookies for the nip.io site, reload, and sign in.")
PY
