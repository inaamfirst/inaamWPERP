$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    $Python = $venvPython
}
elseif ($env:ERP_PYTHON) {
    $Python = $env:ERP_PYTHON
}
else {
    $Python = "python"
}

$safeRepoRoot = $repoRoot -replace "'", "''"
$safePython = $Python -replace "'", "''"
$powershell = "$PSHOME\powershell.exe"
$port = if ($env:ERP_API_PORT) { [int]$env:ERP_API_PORT } else { 8000 }
$apiHost = if ($env:ERP_API_HOST) { $env:ERP_API_HOST } else { "127.0.0.1" }
$healthUrl = "http://${apiHost}:$port/api/v1/health"

function Ensure-PythonModule {
    param(
        [string]$ModuleName,
        [string]$PackageName
    )

    & $Python -c "import $ModuleName" *> $null
    if ($LASTEXITCODE -eq 0) {
        return
    }

    Write-Host "Installing missing Python package: $PackageName"
    & $Python -m pip install $PackageName
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

function Wait-ForApiReady {
    param(
        [string]$Url,
        [int]$TimeoutSeconds = 60
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-RestMethod -Uri $Url -Method Get -TimeoutSec 3
            if ($response.status -eq "healthy") {
                return
            }
        }
        catch {
            Start-Sleep -Seconds 1
        }
    }

    throw "ERP API did not become ready at $Url within $TimeoutSeconds seconds."
}

Ensure-PythonModule -ModuleName "multipart" -PackageName "python-multipart"

& (Join-Path $PSScriptRoot "stop_erp.ps1")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& (Join-Path $PSScriptRoot "migrate.ps1")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$apiArgs = @(
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-Command",
    "`$env:ERP_PYTHON='$safePython'; Set-Location -LiteralPath '$safeRepoRoot'; & '$safePython' -m erp.apps.api"
)

Start-Process -FilePath $powershell -ArgumentList $apiArgs -WindowStyle Hidden
Wait-ForApiReady -Url $healthUrl
# Keep the explicit opt-in marker for compatibility while starting the local
# worker by default. Set ERP_START_WORKER=0 to run the desktop/API only.
$startWorker = ($env:ERP_START_WORKER -eq "1") -or ($env:ERP_START_WORKER -ne "0")
if ($startWorker) {
    $workerArgs = @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        "`$env:ERP_PYTHON='$safePython'; `$env:ERP_WORKER_LOOP='true'; `$env:ERP_WORKER_POLL_SECONDS='5'; Set-Location -LiteralPath '$safeRepoRoot'; & '$safePython' -m erp.apps.worker"
    )
    Start-Process -FilePath $powershell -ArgumentList $workerArgs -WindowStyle Hidden
}
# Start the Web Dashboard
$frontendDir = Join-Path $repoRoot "frontend"
if (Test-Path $frontendDir) {
    $frontendArgs = @(
        "/c",
        "cd ""$frontendDir"" && npm run dev"
    )
    Start-Process -FilePath "cmd.exe" -ArgumentList $frontendArgs -WindowStyle Hidden
}

Write-Host ""
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " ERP API is running!" -ForegroundColor Green
Write-Host " Test it on this PC: http://127.0.0.1:$port/api/v1/health"
Write-Host ""
Write-Host " Web Admin Console is starting..." -ForegroundColor Green
Write-Host " (Please wait 15-20 seconds for it to start)" -ForegroundColor Gray
Write-Host " => http://127.0.0.1:3000" -ForegroundColor Yellow
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host ""

& $Python -m erp.apps.desktop
