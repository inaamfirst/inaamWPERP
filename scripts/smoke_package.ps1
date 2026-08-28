param(
    [string]$DistPath = "release_builds\dist",
    [ValidateRange(10, 180)]
    [int]$StartupTimeoutSeconds = 60,
    [switch]$SkipRuntimeSmoke
)

$ErrorActionPreference = "Stop"

function Assert-PackagedArtifact([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Missing packaged artifact: $Path"
    }
}

function Get-FreeLoopbackPort {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    try {
        $listener.Start()
        return ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
    }
    finally {
        $listener.Stop()
    }
}

function Get-OutputTail([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        return "(no output captured)"
    }
    return ((Get-Content -LiteralPath $Path -Tail 50 -ErrorAction SilentlyContinue) -join [Environment]::NewLine)
}

function Assert-ProcessExit([System.Diagnostics.Process]$Process, [string]$Name, [string]$ErrorLog) {
    if ($Process.ExitCode -ne 0) {
        throw "$Name exited with code $($Process.ExitCode).`n$((Get-OutputTail $ErrorLog))"
    }
}

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$distCandidate = if ([IO.Path]::IsPathRooted($DistPath)) {
    $DistPath
}
else {
    Join-Path $repoRoot $DistPath
}
$distRoot = (Resolve-Path -LiteralPath $distCandidate).Path
$apiExe = Join-Path $distRoot "erp-api\erp-api.exe"
$workerExe = Join-Path $distRoot "erp-worker\erp-worker.exe"
$desktopExe = Join-Path $distRoot "erp-desktop\erp-desktop.exe"
$migrationLauncher = Join-Path $distRoot "migrate_database.ps1"
$requiredPaths = @(
    $apiExe,
    $workerExe,
    $desktopExe,
    (Join-Path $distRoot "start_api.ps1"),
    (Join-Path $distRoot "start_worker.ps1"),
    (Join-Path $distRoot "start_desktop.ps1"),
    $migrationLauncher,
    (Join-Path $distRoot "preflight_production.ps1"),
    (Join-Path $distRoot "install_managed_tasks.ps1"),
    (Join-Path $distRoot "uninstall_managed_tasks.ps1"),
    (Join-Path $distRoot "backup_postgres.ps1"),
    (Join-Path $distRoot "restore_postgres.ps1"),
    (Join-Path $distRoot "env.production.example")
)

foreach ($path in $requiredPaths) {
    Assert-PackagedArtifact $path
}

if ($SkipRuntimeSmoke) {
    Write-Host "Packaged artifact file smoke check passed for $distRoot"
    exit 0
}

$tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$tempRoot = Join-Path $tempBase ("choiceoye-package-smoke-" + [Guid]::NewGuid().ToString("N"))
$tempRootFull = [IO.Path]::GetFullPath($tempRoot)
if (-not $tempRootFull.StartsWith($tempBase, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to use a package smoke directory outside the system temporary directory: $tempRootFull"
}

$environmentNames = @(
    "ERP_CONFIG_FILE",
    "ERP_ENV",
    "ERP_API_HOST",
    "ERP_API_PORT",
    "ERP_API_BASE_URL",
    "ERP_DATABASE_URL",
    "ERP_LOCAL_SQLITE_URL",
    "ERP_LOG_DIR",
    "ERP_SUPPORT_DIAGNOSTICS_DIR",
    "ERP_MEDIA_UPLOAD_DIR",
    "ERP_POSTGRES_BACKUP_DIR",
    "ERP_WORKER_HEARTBEAT_FILE",
    "ERP_WORKER_LOOP",
    "ERP_FORCE_HTTPS",
    "ERP_DOCS_ENABLED",
    "ERP_MIGRATE_ONLY",
    "ERP_PREFLIGHT_ONLY",
    "ERP_PREFLIGHT_SKIP_WORKER_HEARTBEAT",
    "ERP_DESKTOP_SMOKE",
    "ERP_DESKTOP_SMOKE_FILE"
)
$originalEnvironment = @{}
foreach ($name in $environmentNames) {
    $originalEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}

$apiProcess = $null
Push-Location $repoRoot
try {
    New-Item -ItemType Directory -Path $tempRootFull -Force | Out-Null
    $databasePath = Join-Path $tempRootFull "package_smoke.db"
    $databaseUrl = "sqlite:///" + ($databasePath -replace "\\", "/")
    $heartbeatPath = Join-Path $tempRootFull "worker_heartbeat.json"
    $desktopMarker = Join-Path $tempRootFull "desktop_smoke.json"
    $configFile = Join-Path $tempRootFull "smoke.env"
    $port = Get-FreeLoopbackPort

    $smokeConfig = @(
        "ERP_ENV=development",
        "ERP_API_HOST=127.0.0.1",
        "ERP_API_PORT=$port",
        "ERP_API_BASE_URL=http://127.0.0.1:$port",
        "ERP_DATABASE_URL=$databaseUrl",
        "ERP_LOCAL_SQLITE_URL=$databaseUrl",
        "ERP_LOG_DIR=$($tempRootFull -replace '\\', '/')/logs",
        "ERP_SUPPORT_DIAGNOSTICS_DIR=$($tempRootFull -replace '\\', '/')/diagnostics",
        "ERP_MEDIA_UPLOAD_DIR=$($tempRootFull -replace '\\', '/')/uploads",
        "ERP_POSTGRES_BACKUP_DIR=$($tempRootFull -replace '\\', '/')/backups",
        "ERP_WORKER_HEARTBEAT_FILE=$($heartbeatPath -replace '\\', '/')",
        "ERP_WORKER_LOOP=false",
        "ERP_FORCE_HTTPS=false",
        "ERP_DOCS_ENABLED=false"
    ) -join [Environment]::NewLine
    [IO.File]::WriteAllText($configFile, $smokeConfig + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))

    $env:ERP_CONFIG_FILE = $configFile
    $env:ERP_DATABASE_URL = $databaseUrl
    $env:ERP_LOCAL_SQLITE_URL = $databaseUrl
    $env:ERP_API_HOST = "127.0.0.1"
    $env:ERP_API_PORT = "$port"
    $env:ERP_WORKER_LOOP = "false"
    $env:ERP_FORCE_HTTPS = "false"
    $env:ERP_DESKTOP_SMOKE = "1"
    $env:ERP_DESKTOP_SMOKE_FILE = $desktopMarker
    Remove-Item Env:\ERP_MIGRATE_ONLY -ErrorAction SilentlyContinue
    Remove-Item Env:\ERP_PREFLIGHT_ONLY -ErrorAction SilentlyContinue
    Remove-Item Env:\ERP_PREFLIGHT_SKIP_WORKER_HEARTBEAT -ErrorAction SilentlyContinue

    $migrationStdout = Join-Path $tempRootFull "migration.stdout.log"
    $migrationStderr = Join-Path $tempRootFull "migration.stderr.log"
    $migrationArguments = (
        '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $migrationLauncher +
        '" -AppRoot "' + $distRoot + '" -ConfigFile "' + $configFile + '"'
    )
    $migrationProcess = Start-Process -FilePath "powershell.exe" `
        -ArgumentList $migrationArguments `
        -WorkingDirectory $distRoot `
        -RedirectStandardOutput $migrationStdout `
        -RedirectStandardError $migrationStderr `
        -PassThru `
        -Wait `
        -WindowStyle Hidden
    Assert-ProcessExit $migrationProcess "Packaged migration" $migrationStderr

    $apiStdout = Join-Path $tempRootFull "api.stdout.log"
    $apiStderr = Join-Path $tempRootFull "api.stderr.log"
    $apiProcess = Start-Process -FilePath $apiExe `
        -WorkingDirectory (Split-Path -Parent $apiExe) `
        -RedirectStandardOutput $apiStdout `
        -RedirectStandardError $apiStderr `
        -PassThru `
        -WindowStyle Hidden

    $healthUrl = "http://127.0.0.1:$port/api/v1/health"
    $deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    $apiHealthy = $false
    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -TimeoutSec 5
            $payload = $response.Content | ConvertFrom-Json
            if ($response.StatusCode -eq 200 -and $payload.status -eq "healthy") {
                $apiHealthy = $true
                break
            }
        }
        catch {
            # Startup is expected to take a few seconds; process exit is not.
        }
        $apiProcess.Refresh()
        if ($apiProcess.HasExited) {
            throw "Packaged API exited during startup with code $($apiProcess.ExitCode).`n$((Get-OutputTail $apiStderr))"
        }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)

    if (-not $apiHealthy) {
        throw "Packaged API did not become healthy at $healthUrl within $StartupTimeoutSeconds seconds.`n$((Get-OutputTail $apiStderr))"
    }

    $workerStdout = Join-Path $tempRootFull "worker.stdout.log"
    $workerStderr = Join-Path $tempRootFull "worker.stderr.log"
    $workerProcess = Start-Process -FilePath $workerExe `
        -WorkingDirectory (Split-Path -Parent $workerExe) `
        -RedirectStandardOutput $workerStdout `
        -RedirectStandardError $workerStderr `
        -PassThru `
        -Wait `
        -WindowStyle Hidden
    Assert-ProcessExit $workerProcess "Packaged worker" $workerStderr
    if (-not (Test-Path -LiteralPath $heartbeatPath -PathType Leaf)) {
        throw "Packaged worker completed without writing its heartbeat file.`n$((Get-OutputTail $workerStderr))"
    }
    $heartbeat = Get-Content -LiteralPath $heartbeatPath -Raw | ConvertFrom-Json
    if ([string]::IsNullOrWhiteSpace([string]$heartbeat.worker_id)) {
        throw "Packaged worker wrote an invalid heartbeat file."
    }

    $desktopStdout = Join-Path $tempRootFull "desktop.stdout.log"
    $desktopStderr = Join-Path $tempRootFull "desktop.stderr.log"
    $desktopProcess = Start-Process -FilePath $desktopExe `
        -WorkingDirectory (Split-Path -Parent $desktopExe) `
        -RedirectStandardOutput $desktopStdout `
        -RedirectStandardError $desktopStderr `
        -PassThru `
        -Wait `
        -WindowStyle Hidden
    Assert-ProcessExit $desktopProcess "Packaged desktop smoke" $desktopStderr
    if (-not (Test-Path -LiteralPath $desktopMarker -PathType Leaf)) {
        throw "Packaged desktop did not produce its non-GUI smoke marker.`n$((Get-OutputTail $desktopStderr))"
    }
    $desktopSmoke = Get-Content -LiteralPath $desktopMarker -Raw | ConvertFrom-Json
    if ($desktopSmoke.status -ne "ok" -or -not ($desktopSmoke.navigation_items -contains "Products")) {
        throw "Packaged desktop smoke marker is invalid."
    }

    Write-Host "Packaged API, migration, worker, and non-GUI desktop smoke check passed for $distRoot"
}
finally {
    if ($null -ne $apiProcess) {
        $apiProcess.Refresh()
        if (-not $apiProcess.HasExited) {
            Stop-Process -Id $apiProcess.Id -Force -ErrorAction SilentlyContinue
            $apiProcess.WaitForExit()
        }
    }
    foreach ($name in $environmentNames) {
        $previous = $originalEnvironment[$name]
        if ($null -eq $previous) {
            Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue
        }
        else {
            Set-Item -Path "Env:$name" -Value $previous
        }
    }
    Pop-Location
    if (Test-Path -LiteralPath $tempRootFull) {
        $verifyTempRoot = [IO.Path]::GetFullPath($tempRootFull)
        if (-not $verifyTempRoot.StartsWith($tempBase, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove a package smoke directory outside the system temporary directory: $verifyTempRoot"
        }
        Remove-Item -LiteralPath $verifyTempRoot -Recurse -Force
    }
}