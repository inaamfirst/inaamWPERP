# Linux staging deployment

`setup_staging.sh` configures the existing Ubuntu 24.04 DigitalOcean Droplet
for the pinned ERP revision. It must be run as `root` from the DigitalOcean Web
Console because the current home network cannot reach SSH port 22.

## Run

From the repository or from a temporary directory on the Droplet:

```bash
curl -fsSL https://raw.githubusercontent.com/inaamfirst/inaamWPERP/main/deploy/linux/setup_staging.sh -o /root/setup_staging.sh
chmod 700 /root/setup_staging.sh
CERTBOT_EMAIL='your-email@example.com' /root/setup_staging.sh
```

The script deploys the current `main` branch, creates a fresh local PostgreSQL
database, installs the FastAPI API, Next.js frontend, worker, Nginx, HTTPS, and
UFW rules. It generates all application/database secrets and stores the one-time
bootstrap token in `/root/inaam-erp-bootstrap-token` with mode 600.

Run it once on the fresh Droplet. Re-running it intentionally generates new
application/database secrets and invalidates existing sessions.

The URL is `https://159-65-129-218.nip.io`. This hostname resolves to the
Droplet IP through nip.io and is intended for staging only.

## Update an existing staging Droplet

After a release is pushed, update the existing installation from the
DigitalOcean Web Console. These commands preserve `/etc/inaam-erp/staging.env`
and the PostgreSQL data; they do not run the fresh-install setup script:

```bash
cd /opt/inaam-erp
git fetch origin main
git checkout --detach origin/main
chown -R erp:erp /opt/inaam-erp
runuser -u erp -- bash -lc 'cd /opt/inaam-erp/frontend && npm ci && npm run build'
set -a
. /etc/inaam-erp/staging.env
set +a
/opt/inaam-erp/.venv/bin/alembic upgrade head
systemctl restart inaam-erp-api inaam-erp-frontend inaam-erp-worker
systemctl is-active inaam-erp-api inaam-erp-frontend inaam-erp-worker nginx
curl -fsS https://erp.choiceoye.com/api/v1/health
```

Take or verify a DigitalOcean snapshot before updating, and keep the previous
commit available for rollback. Do not replace the environment file or rerun
`setup_staging.sh` for an application-only update.

## First administrator

After the script completes, read the token only inside the Web Console:

```bash
cat /root/inaam-erp-bootstrap-token
```

Call the existing `POST /api/v1/setup/first-use` endpoint over HTTPS with a new
administrator username and password. Do not put the password in this file or in
source control. The endpoint can only complete once.

## Recover a staging login

Do not print or commit `staging.env`; it contains application and database
secrets. For a migration CLI, load it only in the current shell immediately
before running Alembic (as shown above). If a staging administrator cannot sign in, download the
recovery helper and enter the password only at its hidden terminal prompt:

```bash
curl -fsSL https://raw.githubusercontent.com/inaamfirst/inaamWPERP/main/deploy/linux/recover_staging_login.sh \
  -o /root/recover_staging_login.sh
chmod 700 /root/recover_staging_login.sh
/root/recover_staging_login.sh --probe
```

The helper checks the direct API and browser-backend-for-frontend (BFF) login
paths without printing tokens. Use `--reset-password` only if the direct API
probe rejects the password; it resets the `admin` password and clears login
throttles, but leaves all ERP data unchanged.

If the direct API probe succeeds but the BFF probe reports HTTP 400, run the
following repair helper. It adds only `127.0.0.1` and `localhost` to the API's
trusted-host list, then restarts the ERP services; it does not open a public
port or alter database data.

```bash
curl -fsSL https://raw.githubusercontent.com/inaamfirst/inaamWPERP/main/deploy/linux/repair_staging_bff.sh \
  -o /root/repair_staging_bff.sh
chmod 700 /root/repair_staging_bff.sh
/root/repair_staging_bff.sh
```

## Off-server PostgreSQL backups

Create a DigitalOcean Space (or another S3-compatible bucket), then create
`/etc/inaam-erp/backup.env` with mode 600:

```bash
ERP_DATABASE_URL='postgresql+psycopg://...'
S3_ENDPOINT='https://sgp1.digitaloceanspaces.com'
S3_BUCKET='your-private-space-name'
AWS_ACCESS_KEY_ID='your-spaces-key'
AWS_SECRET_ACCESS_KEY='your-spaces-secret'
AWS_DEFAULT_REGION='sgp1'
RETENTION_DAYS=3
```

Test manually:

```bash
sudo cp /etc/inaam-erp/backup.env.example /etc/inaam-erp/backup.env
sudo chmod 600 /etc/inaam-erp/backup.env
sudo nano /etc/inaam-erp/backup.env
sudo /usr/local/sbin/inaam-erp-backup
sudo systemctl enable --now inaam-erp-backup.timer
```

The installer places the backup script at `/usr/local/sbin/inaam-erp-backup`
and creates a daily systemd timer. Never commit `backup.env` or credentials.
