param(
    [string]$HostName = "127.0.0.1",
    [int]$Port = 5432,
    [Parameter(Mandatory = $true)]
    [string]$Database,
    [Parameter(Mandatory = $true)]
    [string]$Username,
    [string]$OutputDir = "runtime_data\postgres_backups"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command pg_dump -ErrorAction SilentlyContinue)) {
    throw "pg_dump was not found. Install PostgreSQL client tools and retry."
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupFile = Join-Path $OutputDir "$Database-$timestamp.dump"

& pg_dump `
    --format=custom `
    --no-owner `
    --no-privileges `
    --host $HostName `
    --port $Port `
    --username $Username `
    --file $backupFile `
    $Database

if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "PostgreSQL backup written to $backupFile"
