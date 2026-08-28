param(
    [Parameter(Mandatory = $true)]
    [string]$BackupFile,
    [string]$HostName = "127.0.0.1",
    [int]$Port = 5432,
    [Parameter(Mandatory = $true)]
    [string]$Database,
    [Parameter(Mandatory = $true)]
    [string]$Username,
    [switch]$ConfirmRestore
)

$ErrorActionPreference = "Stop"

if (-not $ConfirmRestore) {
    throw "Restore is destructive. Re-run with -ConfirmRestore after verifying the backup and target database."
}

if (-not (Test-Path $BackupFile)) {
    throw "Backup file does not exist: $BackupFile"
}

if (-not (Get-Command pg_restore -ErrorAction SilentlyContinue)) {
    throw "pg_restore was not found. Install PostgreSQL client tools and retry."
}

& pg_restore `
    --clean `
    --if-exists `
    --no-owner `
    --no-privileges `
    --host $HostName `
    --port $Port `
    --username $Username `
    --dbname $Database `
    $BackupFile

if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "PostgreSQL restore completed for $Database"
