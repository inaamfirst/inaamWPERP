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

$port = if ($env:ERP_API_PORT) { [int]$env:ERP_API_PORT } else { 8000 }

function Stop-ExistingApiProcesses {
    param([int]$Port)

    try {
        $allProcesses = @(Get-CimInstance Win32_Process -ErrorAction Stop)
    }
    catch {
        Write-Host "Could not inspect existing API processes: $($_.Exception.Message)"
        return
    }

    $apiProcessIds = @(
        $allProcesses |
            Where-Object {
                $_.ProcessId -ne $PID -and
                $_.CommandLine -and
                $_.CommandLine -match 'erp\.apps\.api'
            } |
            Select-Object -ExpandProperty ProcessId
    )

    $listenerProcessIds = @()
    try {
        $listenerProcessIds = @(
            Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
                Select-Object -ExpandProperty OwningProcess -Unique |
                Where-Object { $_ -gt 0 -and $_ -ne $PID }
        )
    }
    catch {
        $listenerProcessIds = @()
    }

    $processIds = @($apiProcessIds + $listenerProcessIds) |
        Where-Object { $_ } |
        Select-Object -Unique
    foreach ($processId in $processIds) {
        $processInfo = $allProcesses | Where-Object { $_.ProcessId -eq $processId } | Select-Object -First 1
        if ($processInfo -and $processInfo.CommandLine -notmatch 'erp\.apps\.api') {
            continue
        }
        try {
            Stop-Process -Id $processId -Force -ErrorAction Stop
            Write-Host "Stopped existing ERP API process $processId"
            Start-Sleep -Milliseconds 150
        }
        catch {
            Write-Host "Could not stop ERP API process ${processId}: $($_.Exception.Message)"
        }
    }
}

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

Ensure-PythonModule -ModuleName "multipart" -PackageName "python-multipart"

Stop-ExistingApiProcesses -Port $port

& (Join-Path $PSScriptRoot "migrate.ps1")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $Python -m erp.apps.api
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
