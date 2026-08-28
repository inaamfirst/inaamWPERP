param(
    [string]$AppRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$ConfigFile = "",
    [string]$ApiTaskName = "ChoiceOye ERP API",
    [string]$WorkerTaskName = "ChoiceOye ERP Worker",
    [string]$HealthUrl = "",
    [switch]$SkipHealthCheck
)

$ErrorActionPreference = "Stop"

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run this script from an elevated PowerShell session."
    }
}

function Resolve-ProductionConfig([string]$Root, [string]$RequestedPath) {
    if ($RequestedPath) {
        if (-not (Test-Path -LiteralPath $RequestedPath)) {
            throw "Production configuration was not found: $RequestedPath"
        }
        return (Resolve-Path -LiteralPath $RequestedPath).Path
    }
    $programData = [Environment]::GetFolderPath(
        [Environment+SpecialFolder]::CommonApplicationData
    )
    $defaultPath = Join-Path $programData "ChoiceOye\Enterprise Commerce ERP\production.env"
    if (-not (Test-Path -LiteralPath $defaultPath)) {
        throw "Create a protected production.env first. Expected: $defaultPath"
    }
    return (Resolve-Path -LiteralPath $defaultPath).Path
}

function Read-ConfigValue([string]$Path, [string]$Name) {
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match "^\s*$([regex]::Escape($Name))=(.+)$") {
            return $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
    return ""
}

function New-ManagedTaskAction([string]$ScriptPath, [string]$Root, [string]$Configuration) {
    $arguments = (
        '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $ScriptPath +
        '" -AppRoot "' + $Root + '" -ConfigFile "' + $Configuration + '"'
    )
    return New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments
}

function Wait-ForApiHealth([string]$Url) {
    $deadline = (Get-Date).AddMinutes(2)
    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 10
            if ($response.StatusCode -eq 200) {
                $payload = $response.Content | ConvertFrom-Json
                if ($payload.status -eq "healthy") {
                    return
                }
            }
        }
        catch {
            # The task may still be starting or the public reverse proxy may be converging.
        }
        Start-Sleep -Seconds 3
    } while ((Get-Date) -lt $deadline)

    throw "API readiness check failed: $Url"
}

Assert-Administrator
$AppRoot = (Resolve-Path -LiteralPath $AppRoot).Path
$ConfigFile = Resolve-ProductionConfig $AppRoot $ConfigFile

$apiLauncher = Join-Path $AppRoot "start_api.ps1"
$workerLauncher = Join-Path $AppRoot "start_worker.ps1"
$preflightLauncher = Join-Path $AppRoot "preflight_production.ps1"
foreach ($path in @($apiLauncher, $workerLauncher, $preflightLauncher)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Missing managed-launch script: $path"
    }
}

$taskSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Days 3650) -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

$apiTask = New-ScheduledTask -Action (New-ManagedTaskAction $apiLauncher $AppRoot $ConfigFile) -Trigger $trigger -Settings $taskSettings -Principal $principal
$workerTask = New-ScheduledTask -Action (New-ManagedTaskAction $workerLauncher $AppRoot $ConfigFile) -Trigger $trigger -Settings $taskSettings -Principal $principal

Register-ScheduledTask -TaskName $ApiTaskName -InputObject $apiTask -Force | Out-Null
Register-ScheduledTask -TaskName $WorkerTaskName -InputObject $workerTask -Force | Out-Null
Start-ScheduledTask -TaskName $ApiTaskName
Start-ScheduledTask -TaskName $WorkerTaskName

if (-not $SkipHealthCheck) {
    if (-not $HealthUrl) {
        $apiBaseUrl = Read-ConfigValue $ConfigFile "ERP_API_BASE_URL"
        if (-not $apiBaseUrl) {
            throw "Set ERP_API_BASE_URL or pass -HealthUrl for the HTTPS readiness check."
        }
        $HealthUrl = "$($apiBaseUrl.TrimEnd('/'))/api/v1/health"
    }
    Wait-ForApiHealth $HealthUrl
}

& $preflightLauncher -AppRoot $AppRoot -ConfigFile $ConfigFile
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "Managed API and worker tasks are installed and healthy."
