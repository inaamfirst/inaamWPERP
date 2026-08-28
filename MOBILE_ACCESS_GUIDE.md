# Mobile, LAN, and Server Access Guide

## Current Limitation

This ERP does not have a browser-based mobile UI yet.
The current user interface is a Windows desktop app built with PySide6.

That means:

- You can run it on a PC.
- You can connect the desktop app to a local or remote FastAPI backend.
- You cannot use the full ERP directly in a phone browser unless a separate web frontend is built later.

## 1. Use It On The Same PC

Use this when one Windows machine runs both the API and the desktop app.

1. Install dependencies.
2. Copy `.env.example` to `.env`.
3. Run the migrations.
4. Start the local stack:

```powershell
.\scripts\run_pc_local.ps1
```

This starts:

- the FastAPI API
- the background worker
- the PySide6 desktop app

## 2. Use It On The Same Wi-Fi / LAN

Use this when the PC stays on and another device on the same network needs to reach the API.

Important:

- If the PC is powered off, the ERP is not available.
- If the PC is running but the API is bound only to `127.0.0.1`, other devices cannot reach it.
- The app still does not become a phone UI. A phone can only reach the backend API unless you build a web frontend.

### Local Network Setup

The PC should use these values:

```powershell
$env:ERP_API_HOST="0.0.0.0"
$env:ERP_API_PORT="8000"
$env:ERP_API_BASE_URL="http://127.0.0.1:8000"
```

These values mean:

- the API listens on all interfaces so other devices can reach it
- the desktop app on the same PC still talks to localhost
- a phone on the same Wi-Fi can reach the API at the PC's LAN IP

If you want the launcher to print a fixed LAN address instead of re-detecting
the current DHCP address every time, set:

```powershell
$env:ERP_LAN_IP="192.168.1.50"
```

This only changes the advertised URL and the browser dev-server origin allowlist.
It does not create a true static IP by itself. For a permanent address, use a
Windows static IP or, preferably, a DHCP reservation on the router.

If you want the one-click launcher, use:

```powershell
.\RUN_ERP_LAN.bat
```

Or from the existing batch wrapper:

```powershell
.\RUN_ERP.bat lan
```

If you are starting the API manually:

```powershell
.\scripts\run_api.ps1
```

Then allow the port through Windows Firewall if needed, find the PC's LAN IP address, for example `192.168.1.20`, and open the API from another device using:

```text
http://192.168.1.20:8000/api/v1/health
```

### If You Want The Desktop App To Use A Remote API

Set the API base URL to the PC or server address:

```powershell
$env:ERP_API_BASE_URL="http://192.168.1.20:8000"
```

The desktop app uses `ERP_API_BASE_URL` when it is set.

## 3. Use It On A Server

Use this when the API and database live on a server and the desktop app runs on a PC.

### Server Side

Use values like these:

```powershell
$env:ERP_ENV="production"
$env:ERP_API_HOST="127.0.0.1"
$env:ERP_API_PORT="8000"
$env:ERP_API_BASE_URL="https://YOURDOMAIN"
$env:ERP_DATABASE_URL="postgresql+psycopg://USER:PASSWORD@DBHOST:5432/DBNAME"
$env:ERP_SECRET_KEY="replace-with-a-long-random-secret"
$env:ERP_BOOTSTRAP_TOKEN="replace-with-a-long-random-bootstrap-token"
$env:ERP_LICENSE_SERVER_ADMIN_KEY="replace-with-a-long-random-admin-key"
$env:ERP_LICENSE_OFFLINE_SIGNING_KEY="replace-with-a-long-random-offline-signing-key"
$env:ERP_FORCE_HTTPS="true"
$env:ERP_WORKER_LOOP="true"
```

Also set `ERP_TRUSTED_HOSTS` and `ERP_TRUSTED_PROXY_IPS` to explicit values
matching your reverse proxy.

Required production direction from the repo:

- `ERP_ENV=production`
- `ERP_DATABASE_URL` must be PostgreSQL
- `ERP_API_BASE_URL` must be a public HTTPS URL
- `ERP_FORCE_HTTPS=true`
- `ERP_WORKER_LOOP=true`
- `ERP_TRUSTED_HOSTS` must be explicit
- `ERP_TRUSTED_PROXY_IPS` must list the reverse proxy

### Desktop Side

Set the desktop app to the server URL:

```powershell
$env:ERP_API_BASE_URL="https://YOURDOMAIN"
```

Then start the desktop app normally.

## 4. Recommended Choice

- One PC only: use local PC mode.
- Same Wi-Fi inside the shop: use LAN mode with the API on the PC.
- Multiple users or remote access: use server mode with HTTPS.

## 5. What To Use On A Phone

If you only need to check API health or build a custom mobile client, the backend can be reached by URL.

If you want full ERP screens on a phone, this codebase needs a web frontend first.
