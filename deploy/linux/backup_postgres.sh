#!/usr/bin/env bash
set -Eeuo pipefail

CONFIG_FILE="${CONFIG_FILE:-/etc/inaam-erp/backup.env}"
[[ -r "$CONFIG_FILE" ]] || { echo "Missing $CONFIG_FILE" >&2; exit 1; }
# shellcheck disable=SC1090
source "$CONFIG_FILE"
: "${ERP_DATABASE_URL:?ERP_DATABASE_URL is required}"
: "${S3_ENDPOINT:?S3_ENDPOINT is required}"
: "${S3_BUCKET:?S3_BUCKET is required}"
: "${AWS_ACCESS_KEY_ID:?AWS_ACCESS_KEY_ID is required}"
: "${AWS_SECRET_ACCESS_KEY:?AWS_SECRET_ACCESS_KEY is required}"
export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-sgp1}"

LOCAL_DIR="${LOCAL_DIR:-/var/lib/inaam-erp/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-3}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FILE="$LOCAL_DIR/enterprise_commerce_erp-$STAMP.dump"
PG_DSN="${ERP_DATABASE_URL/postgresql+psycopg:/postgresql:}"
mkdir -p "$LOCAL_DIR"
chmod 0700 "$LOCAL_DIR"

pg_dump --format=custom --file="$FILE" "$PG_DSN"
aws --endpoint-url "$S3_ENDPOINT" s3 cp "$FILE" "s3://$S3_BUCKET/postgres/$(basename "$FILE")" --only-show-errors
find "$LOCAL_DIR" -type f -name '*.dump' -mtime "+$RETENTION_DAYS" -delete
echo "Uploaded $(basename "$FILE")"
