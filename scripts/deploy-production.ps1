[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$Message,
    [string]$ConfigPath,
    [switch]$StageSafeChanges,
    [switch]$SkipTests,
    [switch]$NoHealthCheck
)

$ErrorActionPreference = "Stop"
$scriptRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Join-Path $scriptRoot "deploy-production.local.psd1"
}
$repoRoot = (Resolve-Path (Join-Path $scriptRoot "..")).Path
Set-Location $repoRoot

function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & git @Arguments
    if ($LASTEXITCODE -ne 0) { throw "git $($Arguments -join ' ') failed." }
}

if (-not (Test-Path -LiteralPath $ConfigPath)) {
    throw "Deployment config not found: $ConfigPath. Copy scripts\deploy-production.local.psd1.example first."
}
$config = Import-PowerShellDataFile -Path $ConfigPath
foreach ($name in 'Transport', 'Branch', 'HealthUrl') {
    if (-not $config.ContainsKey($name) -or [string]::IsNullOrWhiteSpace($config[$name])) {
        throw "Deployment config is missing '$name'."
    }
}
$transport = ([string]$config.Transport).ToLowerInvariant()
if ($transport -notin @('github-actions', 'ssh')) { throw "Transport must be 'github-actions' or 'ssh'." }
if ($transport -eq 'ssh') {
    foreach ($name in 'Host', 'User', 'Port', 'KeyPath') {
        if (-not $config.ContainsKey($name) -or [string]::IsNullOrWhiteSpace($config[$name])) { throw "SSH deployment config is missing '$name'." }
    }
    if (-not (Test-Path -LiteralPath $config.KeyPath)) { throw "SSH key was not found: $($config.KeyPath)" }
} else {
    foreach ($name in 'Repository', 'Workflow') {
        if (-not $config.ContainsKey($name) -or [string]::IsNullOrWhiteSpace($config[$name])) { throw "GitHub Actions config is missing '$name'." }
    }
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { throw "GitHub CLI (gh) is required; install it and run 'gh auth login'." }
}

$branch = (& git branch --show-current).Trim()
if ($branch -ne $config.Branch) {
    throw "Deploy only from '$($config.Branch)'; current branch is '$branch'."
}
Invoke-Git fetch origin $config.Branch
$behind = (& git rev-list --count "HEAD..origin/$($config.Branch)").Trim()
if ([int]$behind -ne 0) {
    throw "Your branch is behind origin/$($config.Branch). Pull/rebase and review it before deployment."
}

if ($StageSafeChanges) {
    # Exclude PC data and generated artifacts, including files that may once
    # have been accidentally tracked. The first secure-release commit untracks them.
    Invoke-Git restore --staged -- runtime_data .pytest_cache .ruff_cache Tree.txt
    Invoke-Git rm --cached --ignore-unmatch -r -- runtime_data .pytest_cache .ruff_cache
    Invoke-Git add --all -- . ':(exclude)runtime_data' ':(exclude).pytest_cache' ':(exclude).ruff_cache' ':(exclude)Tree.txt'
}

& git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    throw "Nothing is staged. Review changes, stage the intended source files, then run this command again."
}

if (-not $SkipTests) {
    $python = if (Test-Path ".\.venv\Scripts\python.exe") { ".\.venv\Scripts\python.exe" } else { "python" }
    & $python -m pytest tests/test_woocommerce_api.py tests/test_auth_vendor_ledger.py
    if ($LASTEXITCODE -ne 0) { throw "Focused WooCommerce/vendor regression tests failed; deployment was not committed." }
}

Invoke-Git commit -m $Message
Invoke-Git push origin $config.Branch
$commit = (& git rev-parse HEAD).Trim()

if ($transport -eq 'ssh') {
    $sshArgs = @('-i', $config.KeyPath, '-p', [string]$config.Port, '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=accept-new', "{0}@{1}" -f $config.User, $config.Host, "sudo /usr/local/sbin/inaam-erp-deploy --commit $commit")
    & ssh @sshArgs
    if ($LASTEXITCODE -ne 0) { throw "Remote deployment failed. The server script attempted rollback when a release had begun." }
} else {
    & gh workflow run $config.Workflow --repo $config.Repository --ref $config.Branch --field "commit=$commit"
    if ($LASTEXITCODE -ne 0) { throw "GitHub Actions deployment could not be dispatched." }
    $run = $null
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        Start-Sleep -Seconds 5
        $json = (& gh run list --repo $config.Repository --workflow $config.Workflow --branch $config.Branch --limit 10 --json databaseId,status,conclusion,headSha | ConvertFrom-Json)
        $run = @($json | Where-Object { $_.headSha -eq $commit } | Select-Object -First 1)
        if ($run -and $run.status -eq 'completed') { break }
    }
    if (-not $run) { throw "Deployment workflow did not appear in GitHub Actions within the expected time." }
    if ($run.status -ne 'completed' -or $run.conclusion -ne 'success') { & gh run view $run.databaseId --repo $config.Repository --log-failed; throw "GitHub Actions deployment failed with conclusion '$($run.conclusion)'." }
}

if (-not $NoHealthCheck) {
    try {
        $response = Invoke-WebRequest -Uri $config.HealthUrl -UseBasicParsing -TimeoutSec 30
        if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 300) { throw "Health endpoint returned HTTP $($response.StatusCode)." }
    } catch { throw "Remote deploy finished, but public health verification failed: $($_.Exception.Message)" }
}

Write-Host "Production deployment succeeded: $commit" -ForegroundColor Green
