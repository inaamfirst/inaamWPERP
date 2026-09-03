$ErrorActionPreference = "Stop"

$PluginRoot = Join-Path (Get-Location) "integrations\wordpress\choiceoye-erp-product-videos"
if (-not (Test-Path -LiteralPath $PluginRoot)) {
    throw "WordPress plugin directory is missing: $PluginRoot"
}

$Php = Get-Command php -ErrorAction SilentlyContinue
if (-not $Php) {
    throw "PHP 8.0 or newer is required to validate the WordPress plugin."
}

$Version = & php -r "echo PHP_VERSION;"
if ([version]$Version -lt [version]"8.0.0") {
    throw "PHP 8.0 or newer is required; found $Version."
}

Get-ChildItem -LiteralPath $PluginRoot -Recurse -Filter *.php | ForEach-Object {
    & php -l $_.FullName
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

& php (Join-Path $PluginRoot "tests\smoke.php")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
