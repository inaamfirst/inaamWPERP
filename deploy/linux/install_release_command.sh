#!/usr/bin/env bash
# One-time installer. Run as root from the DigitalOcean Web Console.
set -Eeuo pipefail

usage() {
  cat >&2 <<'EOF'
Usage: install_release_command.sh --deploy-key-file /path/to/public-key --health-url https://example/api/v1/health

The public key is the .pub half of the SSH key stored on the Windows PC.
EOF
  exit 64
}

[[ "$(id -u)" == "0" ]] || { echo "Run this installer as root." >&2; exit 1; }
KEY_FILE=""
HEALTH_URL=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --deploy-key-file) KEY_FILE="${2:-}"; shift 2 ;;
    --health-url) HEALTH_URL="${2:-}"; shift 2 ;;
    *) usage ;;
  esac
done
[[ -r "$KEY_FILE" && "$HEALTH_URL" =~ ^https:// ]] || usage

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="/opt/inaam-erp"
DEPLOY_USER="erp-deploy"
CONFIG_FILE="/etc/inaam-erp/release.env"

id "$DEPLOY_USER" >/dev/null 2>&1 || useradd --create-home --shell /bin/sh "$DEPLOY_USER"
install -d -m 0700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh"
install -m 0750 -o root -g root "$SCRIPT_DIR/inaam-erp-deploy" /usr/local/sbin/inaam-erp-deploy

cat >/usr/local/sbin/inaam-erp-deploy-gateway <<'EOF'
#!/bin/sh
set -eu
if ! printf '%s\n' "${SSH_ORIGINAL_COMMAND:-}" | grep -Eq '^sudo /usr/local/sbin/inaam-erp-deploy --commit [0-9a-f]{40}$'; then
  echo 'This deployment key may only run the ERP deployment command.' >&2
  exit 126
fi
commit="${SSH_ORIGINAL_COMMAND##*--commit }"
exec sudo /usr/local/sbin/inaam-erp-deploy --commit "$commit"
EOF
chmod 0755 /usr/local/sbin/inaam-erp-deploy-gateway

PUBLIC_KEY="$(cat "$KEY_FILE")"
printf 'command="/usr/local/sbin/inaam-erp-deploy-gateway",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty %s\n' \
  "$PUBLIC_KEY" >"/home/$DEPLOY_USER/.ssh/authorized_keys"
chown "$DEPLOY_USER:$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh/authorized_keys"
chmod 0600 "/home/$DEPLOY_USER/.ssh/authorized_keys"

cat >/etc/sudoers.d/inaam-erp-deploy <<'EOF'
erp-deploy ALL=(root) NOPASSWD: /usr/local/sbin/inaam-erp-deploy --commit *
EOF
chmod 0440 /etc/sudoers.d/inaam-erp-deploy
visudo -cf /etc/sudoers.d/inaam-erp-deploy

if [[ ! -f "$CONFIG_FILE" ]]; then
  cat >"$CONFIG_FILE" <<EOF
APP_ROOT=$APP_ROOT
APP_USER=erp
ENV_FILE=/etc/inaam-erp/staging.env
HEALTH_URL=$HEALTH_URL
BRANCH=main
BACKUP_ROOT=/var/lib/inaam-erp/release-backups
EOF
  chmod 0600 "$CONFIG_FILE"
fi
install -d -m 0700 /var/lib/inaam-erp/release-backups
echo "Deployment key installed for $DEPLOY_USER. Test from the PC with the local deploy script."
