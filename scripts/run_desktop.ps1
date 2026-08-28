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

& $Python -m erp.apps.desktop
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
