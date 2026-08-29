#!/usr/bin/env bash
set -Eeuo pipefail

# Permit only the local Next.js BFF to use its loopback Host header when it
# calls FastAPI. The API itself remains bound to 127.0.0.1 and is not exposed.

APP_USER="${APP_USER:-erp}"
ENV_FILE="${ENV_FILE:-/etc/inaam-erp/staging.env}"

if [[ "$(id -u)" != 0 ]]; then
  echo "Run this helper as root from the DigitalOcean Web Console." >&2
  exit 1
fi
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing ERP environment file: $ENV_FILE" >&2
  exit 1
fi

API_URL="$(sed -n 's/^ERP_API_BASE_URL=https:\/\/\([^/]*\).*$/\1/p' "$ENV_FILE" | head -n 1)"
if [[ -z "$API_URL" || ! "$API_URL" =~ ^[A-Za-z0-9.-]+(:[0-9]+)?$ ]]; then
  echo "Could not read a valid HTTPS host from $ENV_FILE." >&2
  exit 1
fi

sed -i "s|^ERP_TRUSTED_HOSTS=.*$|ERP_TRUSTED_HOSTS='[\"$API_URL\",\"127.0.0.1\",\"localhost\"]'|" "$ENV_FILE"
chown root:"$APP_USER" "$ENV_FILE"
chmod 0640 "$ENV_FILE"

systemctl restart inaam-erp-api inaam-erp-frontend inaam-erp-worker
systemctl is-active --quiet inaam-erp-api inaam-erp-frontend inaam-erp-worker

echo "BFF trusted-host repair applied. Run /root/recover_staging_login.sh --probe next."
