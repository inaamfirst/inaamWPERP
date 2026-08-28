param(
    [string]$AppRoot = (Get-Location).Path,
    [string]$ConfigFile = "",
    [switch]$SkipWorkerHeartbeat
)

$ErrorActionPreference = "Stop"

$AppRoot = (Resolve-Path -LiteralPath $AppRoot).Path
if (-not $ConfigFile) {
    $programData = [Environment]::GetFolderPath(
        [Environment+SpecialFolder]::CommonApplicationData
    )
    $managedConfig = Join-Path $programData "ChoiceOye\Enterprise Commerce ERP\production.env"
    $ConfigFile = if (Test-Path -LiteralPath $managedConfig) {
        $managedConfig
    }
    else {
        Join-Path $AppRoot ".env"
    }
}
if (-not (Test-Path -LiteralPath $ConfigFile)) {
    throw "Production configuration was not found: $ConfigFile"
}

$env:ERP_CONFIG_FILE = (Resolve-Path -LiteralPath $ConfigFile).Path
$env:ERP_PREFLIGHT_ONLY = "1"
if ($SkipWorkerHeartbeat) {
    $env:ERP_PREFLIGHT_SKIP_WORKER_HEARTBEAT = "1"
}
else {
    Remove-Item Env:\ERP_PREFLIGHT_SKIP_WORKER_HEARTBEAT -ErrorAction SilentlyContinue
}

Set-Location $AppRoot
& (Join-Path $AppRoot "erp-api\erp-api.exe")
exit $LASTEXITCODE
