param(
    [switch]$SkipChecks,
    [switch]$SkipPackageSmoke
)

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

if (-not $SkipChecks) {
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check.ps1
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

& $Python -m pip install -e ".[build]"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$releaseRoot = Join-Path (Get-Location) "release_builds"
$distPath = Join-Path $releaseRoot "dist"
$workPath = Join-Path $releaseRoot "work"
New-Item -ItemType Directory -Force -Path $distPath | Out-Null
New-Item -ItemType Directory -Force -Path $workPath | Out-Null

$specs = @(
    "deploy\pyinstaller\erp-api.spec",
    "deploy\pyinstaller\erp-worker.spec",
    "deploy\pyinstaller\erp-desktop.spec"
)

foreach ($spec in $specs) {
    & $Python -m PyInstaller --noconfirm --clean --distpath $distPath --workpath $workPath $spec
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Copy-Item -Path deploy\windows\*.ps1 -Destination $distPath -Force
Copy-Item -Path scripts\backup_postgres.ps1 -Destination (Join-Path $distPath "backup_postgres.ps1") -Force
Copy-Item -Path scripts\restore_postgres.ps1 -Destination (Join-Path $distPath "restore_postgres.ps1") -Force
Copy-Item -Path deploy\windows\env.production.example -Destination $distPath -Force

if (-not $SkipPackageSmoke) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File scripts\smoke_package.ps1 -DistPath $distPath
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host "Packaged build written to $distPath"
