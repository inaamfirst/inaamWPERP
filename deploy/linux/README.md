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

## First administrator

After the script completes, read the token only inside the Web Console:

```bash
cat /root/inaam-erp-bootstrap-token
```

Call the existing `POST /api/v1/setup/first-use` endpoint over HTTPS with a new
administrator username and password. Do not put the password in this file or in
source control. The endpoint can only complete once.

## Recover a staging login

Do not source `staging.env` in a shell: it is a systemd environment file and
contains JSON values. If a staging administrator cannot sign in, download the
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
