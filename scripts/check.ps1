$ErrorActionPreference = "Stop"

$Python = $env:ERP_PYTHON
if (-not $Python) {
    if (Test-Path ".\.venv\Scripts\python.exe") {
        $Python = ".\.venv\Scripts\python.exe"
    }
    else {
        $Python = "python"
    }
}

& $Python -m ruff check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python -m pytest
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python -c "from erp.apps.api.main import create_app; app = create_app(); assert app.title"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python -c "from alembic.config import Config; cfg = Config('alembic.ini'); assert cfg.get_main_option('script_location') == 'migrations'"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$runtimeDir = Join-Path (Get-Location) "runtime_data"
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
$smokeDb = Join-Path $runtimeDir "check_alembic_smoke.db"
if (Test-Path $smokeDb) { Remove-Item $smokeDb -Force }

$previousDatabaseUrl = $env:ERP_DATABASE_URL
$smokeDbUrl = ($smokeDb -replace "\\", "/")
$env:ERP_DATABASE_URL = "sqlite:///$smokeDbUrl"
try {
    & $Python -m alembic -c alembic.ini upgrade head
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally {
    if ($null -eq $previousDatabaseUrl) {
        Remove-Item Env:\ERP_DATABASE_URL -ErrorAction SilentlyContinue
    }
    else {
        $env:ERP_DATABASE_URL = $previousDatabaseUrl
    }
    if (Test-Path $smokeDb) { Remove-Item $smokeDb -Force }
}
