#!/usr/bin/env bash
set -Eeuo pipefail

# ChoiceOye ERP staging installer for a fresh Ubuntu 24.04 Droplet.
# Run this script as root from the DigitalOcean Web Console.

APP_USER="${APP_USER:-erp}"
APP_ROOT="${APP_ROOT:-/opt/inaam-erp}"
STATE_ROOT="${STATE_ROOT:-/var/lib/inaam-erp}"
CONFIG_DIR="${CONFIG_DIR:-/etc/inaam-erp}"
ENV_FILE="$CONFIG_DIR/staging.env"
REPO_URL="${REPO_URL:-https://github.com/inaamfirst/inaamWPERP.git}"
REPO_REF="${REPO_REF:-faef8aa}"
ERP_HOSTNAME="${ERP_HOSTNAME:-159-65-129-218.nip.io}"
DB_NAME="${DB_NAME:-enterprise_commerce_erp}"
DB_USER="${DB_USER:-erp_app_user}"
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"

if [[ "$(id -u)" != 0 ]]; then
  echo "Run this script as root from the DigitalOcean Web Console." >&2
  exit 1
fi

if [[ ! "$ERP_HOSTNAME" =~ ^[A-Za-z0-9.-]+$ ]]; then
  echo "ERP_HOSTNAME contains invalid characters." >&2
  exit 1
fi
if [[ ! "$DB_NAME" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ || ! "$DB_USER" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]]; then
  echo "DB_NAME and DB_USER must contain only letters, numbers, and underscores." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
echo "==> Installing operating-system packages"
apt-get update
apt-get install -y \
  ca-certificates curl git build-essential libpq-dev openssl \
  python3 python3-venv python3-pip \
  postgresql postgresql-contrib postgresql-client \
  nginx certbot python3-certbot-nginx ufw unzip

if ! command -v node >/dev/null 2>&1 || [[ "$(node -p 'process.versions.node.split(".")[0]')" -lt 20 ]]; then
  echo "==> Installing Node.js 20 LTS"
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
fi

NPM_BIN="$(command -v npm)"

if ! command -v aws >/dev/null 2>&1; then
  echo "==> Installing AWS CLI v2 (used for S3-compatible Spaces backups)"
  if [[ "$(uname -m)" != "x86_64" ]]; then
    echo "This installer currently supports AWS CLI on x86_64 only." >&2
    exit 1
  fi
  AWS_TMP="$(mktemp -d)"
  curl -fsSL https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip \
    -o "$AWS_TMP/awscliv2.zip"
  unzip -q "$AWS_TMP/awscliv2.zip" -d "$AWS_TMP"
  "$AWS_TMP/aws/install" --update
  rm -rf "$AWS_TMP"
fi

echo "==> Creating service account and directories"
if ! id "$APP_USER" >/dev/null 2>&1; then
  useradd --system --home-dir "$STATE_ROOT" --shell /usr/sbin/nologin "$APP_USER"
fi
install -d -o "$APP_USER" -g "$APP_USER" "$APP_ROOT" "$STATE_ROOT" \
  "$STATE_ROOT/logs" "$STATE_ROOT/uploads" "$STATE_ROOT/diagnostics" \
  "$STATE_ROOT/backups" "$STATE_ROOT/license"
install -d -m 0750 -o root -g "$APP_USER" "$CONFIG_DIR"

echo "==> Fetching repository at $REPO_REF"
if [[ -d "$APP_ROOT/.git" ]]; then
  git -c safe.directory="$APP_ROOT" -C "$APP_ROOT" fetch --depth=50 origin main
else
  if [[ -e "$APP_ROOT" ]] && ! rmdir "$APP_ROOT" 2>/dev/null; then
    echo "$APP_ROOT exists and is not an empty Git checkout; refusing to overwrite it." >&2
    exit 1
  fi
  git clone --filter=blob:none "$REPO_URL" "$APP_ROOT"
fi
git -c safe.directory="$APP_ROOT" -C "$APP_ROOT" fetch --depth=50 origin main
git -c safe.directory="$APP_ROOT" -C "$APP_ROOT" checkout --force "$REPO_REF"
chown -R "$APP_USER:$APP_USER" "$APP_ROOT"

echo "==> Creating PostgreSQL role and database"
systemctl enable --now postgresql
DB_PASSWORD="$(openssl rand -hex 32)"
if runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1; then
  runuser -u postgres -- psql -v ON_ERROR_STOP=1 -c "ALTER ROLE \"$DB_USER\" WITH LOGIN PASSWORD '$DB_PASSWORD';"
else
  runuser -u postgres -- psql -v ON_ERROR_STOP=1 -c "CREATE ROLE \"$DB_USER\" LOGIN PASSWORD '$DB_PASSWORD';"
fi
if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1; then
  runuser -u postgres -- createdb -O "$DB_USER" "$DB_NAME"
fi
runuser -u postgres -- psql -v ON_ERROR_STOP=1 -c "ALTER DATABASE \"$DB_NAME\" OWNER TO \"$DB_USER\";"

echo "==> Creating application secrets"
SECRET_KEY="$(openssl rand -hex 48)"
BOOTSTRAP_TOKEN="$(openssl rand -hex 32)"
LICENSE_ADMIN_KEY="$(openssl rand -hex 32)"
LICENSE_SIGNING_KEY="$(openssl rand -hex 48)"
cat > "$ENV_FILE" <<EOF
ERP_ENV=staging
ERP_APP_NAME=Enterprise Commerce ERP
ERP_API_HOST=127.0.0.1
ERP_API_PORT=8000
ERP_API_PREFIX=/api/v1
ERP_API_BASE_URL=https://$ERP_HOSTNAME
ERP_API_INTERNAL_URL=http://127.0.0.1:8000
ERP_DATABASE_URL=postgresql+psycopg://$DB_USER:$DB_PASSWORD@127.0.0.1:5432/$DB_NAME
ERP_LOCAL_SQLITE_URL=sqlite:///$STATE_ROOT/local_cache.db
ERP_SECRET_KEY=$SECRET_KEY
ERP_BOOTSTRAP_TOKEN=$BOOTSTRAP_TOKEN
ERP_SESSION_TTL_HOURS=12
ERP_ACCESS_TOKEN_TTL_MINUTES=30
ERP_REFRESH_TOKEN_TTL_HOURS=24
ERP_REMEMBER_ME_TTL_DAYS=30
ERP_ACTION_TOKEN_TTL_MINUTES=60
ERP_LOGIN_ATTEMPT_LIMIT=5
ERP_LOGIN_ATTEMPT_WINDOW_MINUTES=15
ERP_LOGIN_BLOCK_MINUTES=15
ERP_AUTH_RECORD_RETENTION_DAYS=90
ERP_AUTH_THROTTLE_RETENTION_DAYS=30
ERP_ALLOW_NEGATIVE_VENDOR_STOCK=false
ERP_BASE_CURRENCY=PKR
ERP_SMTP_HOST=
ERP_SMTP_PORT=587
ERP_SMTP_USERNAME=
ERP_SMTP_PASSWORD=
ERP_SMTP_FROM_EMAIL=
ERP_SMTP_USE_TLS=true
ERP_LOG_LEVEL=INFO
ERP_LOG_DIR=$STATE_ROOT/logs
ERP_LOG_MAX_BYTES=5242880
ERP_LOG_BACKUP_COUNT=5
ERP_LICENSE_SERVER_URL=
ERP_LICENSE_SERVER_ADMIN_KEY=$LICENSE_ADMIN_KEY
ERP_LICENSE_OFFLINE_SIGNING_KEY=$LICENSE_SIGNING_KEY
ERP_LICENSE_DEVICE_ID=staging
ERP_LICENSE_OFFLINE_FILE=$STATE_ROOT/license/offline_license.json
ERP_SUPPORT_DIAGNOSTICS_DIR=$STATE_ROOT/diagnostics
ERP_MEDIA_UPLOAD_DIR=$STATE_ROOT/uploads
ERP_POSTGRES_BACKUP_DIR=$STATE_ROOT/backups
ERP_WORKER_HEARTBEAT_FILE=$STATE_ROOT/worker_heartbeat.json
ERP_DOCS_ENABLED=false
ERP_TRUSTED_HOSTS=["$ERP_HOSTNAME"]
ERP_TRUSTED_PROXY_IPS=["127.0.0.1","::1"]
ERP_CORS_ORIGINS=[]
ERP_FORCE_HTTPS=true
ERP_WHATSAPP_ENABLED=false
ERP_PUSH_ENABLED=false
ERP_PUSH_VAPID_PUBLIC_KEY=
ERP_PUSH_VAPID_PRIVATE_KEY=
ERP_PUSH_VAPID_SUBJECT=mailto:staging@$ERP_HOSTNAME
ERP_PUSH_TTL_SECONDS=300
ERP_PUSH_MAX_ATTEMPTS=5
ERP_PUSH_POLL_SECONDS=5
ERP_WORKER_LOOP=true
ERP_WORKER_POLL_SECONDS=10
ERP_MAX_REQUEST_SIZE_MB=10
EOF
chown root:"$APP_USER" "$ENV_FILE"
chmod 0640 "$ENV_FILE"
printf '%s\n' "$BOOTSTRAP_TOKEN" > /root/inaam-erp-bootstrap-token
chmod 0600 /root/inaam-erp-bootstrap-token

echo "==> Creating Python environment and building frontend"
if [[ -d "$APP_ROOT/.venv" ]]; then
  # A previous interrupted run can leave root-owned editable-install metadata.
  # The virtual environment is disposable; application data lives in STATE_ROOT.
  rm -rf "$APP_ROOT/.venv"
fi
runuser -u "$APP_USER" -- "$PYTHON_BIN" -m venv "$APP_ROOT/.venv"
runuser -u "$APP_USER" -- "$APP_ROOT/.venv/bin/python" -m pip install --upgrade pip
runuser -u "$APP_USER" -- env ERP_CONFIG_FILE="$ENV_FILE" \
  "$APP_ROOT/.venv/bin/pip" install -e "$APP_ROOT"
runuser -u "$APP_USER" -- bash -c "cd '$APP_ROOT/frontend' && npm ci && npm run build"

echo "==> Applying Alembic migrations"
runuser -u "$APP_USER" -- env ERP_CONFIG_FILE="$ENV_FILE" ERP_MIGRATE_ONLY=1 \
  "$APP_ROOT/.venv/bin/erp-api"

echo "==> Installing systemd services"
cat > /etc/systemd/system/inaam-erp-api.service <<EOF
[Unit]
Description=Inaam ERP FastAPI API
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_ROOT
EnvironmentFile=$ENV_FILE
ExecStart=$APP_ROOT/.venv/bin/erp-api
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/inaam-erp-worker.service <<EOF
[Unit]
Description=Inaam ERP background worker
After=network-online.target postgresql.service inaam-erp-api.service
Wants=network-online.target

[Service]
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_ROOT
EnvironmentFile=$ENV_FILE
ExecStart=$APP_ROOT/.venv/bin/erp-worker
Restart=always
RestartSec=10
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/inaam-erp-frontend.service <<EOF
[Unit]
Description=Inaam ERP Next.js frontend
After=network-online.target inaam-erp-api.service
Wants=network-online.target

[Service]
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_ROOT/frontend
EnvironmentFile=$ENV_FILE
Environment=NODE_ENV=production
Environment=HOSTNAME=127.0.0.1
Environment=PORT=3000
ExecStart=$NPM_BIN run start -- -H 127.0.0.1 -p 3000
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

echo "==> Configuring Nginx"
cat > /etc/nginx/sites-available/inaam-erp <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name $ERP_HOSTNAME;

    client_max_body_size 10m;

    location /api/v1/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
EOF
ln -sfn /etc/nginx/sites-available/inaam-erp /etc/nginx/sites-enabled/inaam-erp
rm -f /etc/nginx/sites-enabled/default
nginx -t

echo "==> Enabling firewall and services"
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable
systemctl daemon-reload
systemctl enable postgresql nginx inaam-erp-api inaam-erp-worker inaam-erp-frontend
systemctl restart postgresql nginx inaam-erp-api inaam-erp-worker inaam-erp-frontend

echo "==> Requesting HTTPS certificate"
if [[ -z "${CERTBOT_EMAIL:-}" ]]; then
  read -r -p "Email for Let's Encrypt expiry notices: " CERTBOT_EMAIL
fi
if [[ -z "$CERTBOT_EMAIL" ]]; then
  echo "An email address is required for the certificate. Re-run with CERTBOT_EMAIL=you@example.com." >&2
  exit 1
fi
certbot --nginx --non-interactive --agree-tos --redirect \
  --email "$CERTBOT_EMAIL" -d "$ERP_HOSTNAME"
systemctl reload nginx

echo "==> Installing off-server backup timer (disabled until credentials are configured)"
if [[ -f "$APP_ROOT/deploy/linux/backup_postgres.sh" ]]; then
  install -m 0750 -o root -g root "$APP_ROOT/deploy/linux/backup_postgres.sh" /usr/local/sbin/inaam-erp-backup
else
  # The pinned application commit predates these deployment-only helpers.
  curl -fsSL https://raw.githubusercontent.com/inaamfirst/inaamWPERP/main/deploy/linux/backup_postgres.sh \
    -o /usr/local/sbin/inaam-erp-backup
  chown root:root /usr/local/sbin/inaam-erp-backup
  chmod 0750 /usr/local/sbin/inaam-erp-backup
fi
cat > "$CONFIG_DIR/backup.env.example" <<EOF
ERP_DATABASE_URL=postgresql://$DB_USER:$DB_PASSWORD@127.0.0.1:5432/$DB_NAME
S3_ENDPOINT=https://sgp1.digitaloceanspaces.com
S3_BUCKET=replace-with-private-space-name
AWS_ACCESS_KEY_ID=replace-with-spaces-key
AWS_SECRET_ACCESS_KEY=replace-with-spaces-secret
AWS_DEFAULT_REGION=sgp1
RETENTION_DAYS=3
EOF
chmod 0640 "$CONFIG_DIR/backup.env.example"
cat > /etc/systemd/system/inaam-erp-backup.service <<'EOF'
[Unit]
Description=Inaam ERP PostgreSQL off-server backup
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/inaam-erp-backup
EOF
cat > /etc/systemd/system/inaam-erp-backup.timer <<'EOF'
[Unit]
Description=Daily Inaam ERP PostgreSQL backup

[Timer]
OnCalendar=*-*-* 02:30:00 UTC
Persistent=true

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload

echo
echo "Deployment completed."
echo "URL: https://$ERP_HOSTNAME"
echo "Bootstrap token is saved in /root/inaam-erp-bootstrap-token (mode 600)."
echo "Create /etc/inaam-erp/backup.env from backup.env.example, then enable inaam-erp-backup.timer."
echo "Create the first administrator through POST /api/v1/setup/first-use after HTTPS is verified."
