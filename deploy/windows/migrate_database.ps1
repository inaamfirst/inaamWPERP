param(
    [string]$AppRoot = (Get-Location).Path,
    [string]$ConfigFile = ""
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
$env:ERP_MIGRATE_ONLY = "1"
Remove-Item Env:\ERP_PREFLIGHT_ONLY -ErrorAction SilentlyContinue
Set-Location $AppRoot
& (Join-Path $AppRoot "erp-api\erp-api.exe")
exit $LASTEXITCODE