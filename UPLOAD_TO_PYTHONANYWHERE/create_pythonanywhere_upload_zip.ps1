$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location -LiteralPath $RepoRoot

$BuildRoot = Join-Path $RepoRoot "build_output"
$StageRoot = Join-Path $BuildRoot "pythonanywhere_upload"
$ZipPath = Join-Path $BuildRoot "enterprise-commerce-erp-pythonanywhere.zip"

New-Item -ItemType Directory -Force -Path $BuildRoot | Out-Null
if (Test-Path $StageRoot) {
    $ResolvedStage = Resolve-Path $StageRoot
    $ResolvedBuild = Resolve-Path $BuildRoot
    if (-not $ResolvedStage.Path.StartsWith($ResolvedBuild.Path)) {
        throw "Refusing to clean staging folder outside build_output."
    }
    Remove-Item -LiteralPath $StageRoot -Recurse -Force
}
if (Test-Path $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}
New-Item -ItemType Directory -Force -Path $StageRoot | Out-Null

$includePaths = @(
    ".env.example",
    "alembic.ini",
    "pyproject.toml",
    "README.md",
    ".github",
    "deploy",
    "docs",
    "erp",
    "migrations",
    "scripts",
    "tests",
    "UPLOAD_TO_PYTHONANYWHERE"
)

foreach ($relativePath in $includePaths) {
    if (-not (Test-Path $relativePath)) {
        continue
    }
    $source = Resolve-Path $relativePath
    $destination = Join-Path $StageRoot $relativePath
    if ((Get-Item $source).PSIsContainer) {
        New-Item -ItemType Directory -Force -Path $destination | Out-Null
        Copy-Item -LiteralPath $source -Destination (Split-Path $destination -Parent) -Recurse -Force
    }
    else {
        New-Item -ItemType Directory -Force -Path (Split-Path $destination -Parent) | Out-Null
        Copy-Item -LiteralPath $source -Destination $destination -Force
    }
}

$cleanupPatterns = @(
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "*.pyc",
    "*.pyo"
)

foreach ($pattern in $cleanupPatterns) {
    Get-ChildItem -LiteralPath $StageRoot -Recurse -Force -Filter $pattern |
        Remove-Item -Recurse -Force
}

$forbiddenPatterns = @(
    ".env",
    ".venv",
    "venv",
    "env",
    "runtime_data",
    "runtime_logs",
    "logs",
    "release_builds",
    "build_output",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".git",
    ".agents",
    "enterprise_commerce_erp.egg-info",
    "*.db",
    "*.pyc",
    "*.pyo",
    "*.sqlite",
    "*.sqlite3",
    "*.zip",
    "*.pfx",
    "*.p12",
    "*.pem",
    "*.key",
    ".wwebjs_auth",
    ".wwebjs_cache",
    "ID Passwords"
)

$forbiddenFiles = Get-ChildItem -LiteralPath $StageRoot -Recurse -Force | Where-Object {
    $item = $_
    $relative = $item.FullName.Substring($StageRoot.Length).TrimStart("\")
    foreach ($pattern in $forbiddenPatterns) {
        if ($item.Name -like $pattern -or $relative -like $pattern -or $relative -like "*\$pattern\*") {
            return $true
        }
    }
    return $false
}

if ($forbiddenFiles) {
    $paths = $forbiddenFiles | Select-Object -ExpandProperty FullName
    throw "Forbidden file(s) found in PythonAnywhere upload staging: $($paths -join ', ')"
}

Compress-Archive -Path (Join-Path $StageRoot "*") -DestinationPath $ZipPath -CompressionLevel Optimal
Write-Host "PythonAnywhere upload ZIP created:"
Write-Host $ZipPath
