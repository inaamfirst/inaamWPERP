$ErrorActionPreference = "Stop"
$Python = $env:ERP_PYTHON
if (-not $Python) {
    $Python = "python"
}

& $Python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python -m pip install -e ".[dev]"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
