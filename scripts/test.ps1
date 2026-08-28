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

& $Python -m pytest
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
