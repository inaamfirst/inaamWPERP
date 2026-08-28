param(
    [string]$DistPath = "release_builds\dist",
    [string]$InnoCompiler = "",
    [switch]$SkipPackageSmoke
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $DistPath)) {
    throw "Missing package directory: $DistPath. Run scripts\build_package.ps1 first."
}

if (-not $SkipPackageSmoke) {
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\smoke_package.ps1 -DistPath $DistPath
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$forbiddenNames = @(
    ".env",
    ".wwebjs_auth",
    ".wwebjs_cache",
    "ID Passwords"
)
$forbiddenExtensions = @(
    ".db",
    ".sqlite",
    ".sqlite3",
    ".pfx",
    ".p12",
    ".pem",
    ".key"
)

$forbidden = Get-ChildItem -Path $DistPath -Force -Recurse | Where-Object {
    ($forbiddenNames -contains $_.Name) -or ($forbiddenExtensions -contains $_.Extension)
}

if ($forbidden) {
    $paths = $forbidden | Select-Object -ExpandProperty FullName
    throw "Forbidden file(s) found in installer source: $($paths -join ', ')"
}

if (-not $InnoCompiler) {
    $candidatePaths = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )
    $InnoCompiler = $candidatePaths | Where-Object { Test-Path $_ } | Select-Object -First 1
}

if (-not $InnoCompiler) {
    throw "Inno Setup compiler not found. Install Inno Setup 6 or pass -InnoCompiler."
}

& $InnoCompiler "deploy\inno\installer.iss"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Installer build completed under release_builds\installer"
