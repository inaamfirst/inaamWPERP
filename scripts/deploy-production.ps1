[CmdletBinding()]
param(
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
$Message = if ([string]::IsNullOrWhiteSpace($Message)) {
    "Deploy latest local ERP changes $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
} else {
    $Message
}
$repoRoot = (Resolve-Path (Join-Path $scriptRoot "..")).Path
Set-Location $repoRoot

function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    # Prevent Git's automatic maintenance from prompting while Windows or
    # antivirus software has a .git object directory open.
    & git -c gc.auto=0 @Arguments
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
# Do not let Git's background auto-GC interrupt deployment with Windows file
# deletion prompts when an editor or antivirus has a .git object open.
Invoke-Git fetch origin $config.Branch
$behind = (& git rev-list --count "HEAD..origin/$($config.Branch)").Trim()
if ([int]$behind -ne 0) {
    throw "Your branch is behind origin/$($config.Branch). Pull/rebase and review it before deployment."
}

if ($StageSafeChanges) {
    # Rebuild the index from the working tree while excluding PC-only data,
    # local deployment helpers, archives, and generated files.
    Invoke-Git reset -- .
    $localOnlyPaths = @(
        'DEPLOY_TO_PRODUCTION.bat',
        'Run Manualy - DEPLOY_TO_PRODUCTION.txt',
        'Run Manualy - DEPLOY_TO_PRODUCTION - Copy.txt',
        'Tree.txt',
        'runtime_data',
        '.pytest_cache',
        '.ruff_cache'
    )
    Invoke-Git rm --cached --ignore-unmatch -r -- @localOnlyPaths
    # The exclusions are in .gitignore, so a plain add avoids Windows Git
    # pathspec parsing issues while still leaving those files out.
    Invoke-Git -c advice.addIgnoredFile=false add --all -- .
}

& git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Host "No deployable source changes detected. Production was not changed." -ForegroundColor Yellow
    exit 0
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
    function Get-DeploymentRun {
        $json = (& gh run list --repo $config.Repository --workflow $config.Workflow --branch $config.Branch --limit 20 --json databaseId,status,conclusion,headSha,url | ConvertFrom-Json)
        return @($json | Where-Object { $_.headSha -eq $commit } | Select-Object -First 1)
    }

    function Wait-ForDeploymentRun {
        param([Parameter(Mandatory)]$Run)
        # Ten minutes gives GitHub-hosted runners enough time to leave a
        # transient queue without masking a genuinely stuck run.
        for ($attempt = 0; $attempt -lt 120; $attempt++) {
            Start-Sleep -Seconds 5
            $current = (& gh run view $Run.databaseId --repo $config.Repository --json status,conclusion,url | ConvertFrom-Json)
            if ($current.status -eq 'completed') { return $current }
        }
        return (& gh run view $Run.databaseId --repo $config.Repository --json status,conclusion,url | ConvertFrom-Json)
    }

    $run = $null
    for ($attempt = 0; $attempt -lt 30 -and -not $run; $attempt++) {
        Start-Sleep -Seconds 2
        $run = Get-DeploymentRun
    }
    if (-not $run) { throw "Deployment workflow did not appear in GitHub Actions." }

    $result = Wait-ForDeploymentRun -Run $run
    $queueStatuses = @('queued', 'waiting', 'requested', 'pending')
    if ($queueStatuses -contains $result.status) {
        Write-Warning "Deployment run $($run.databaseId) remained queued for 10 minutes. Cancelling and retrying once."
        & gh run cancel $run.databaseId --repo $config.Repository
        if ($LASTEXITCODE -ne 0) {
            Start-Process $run.url
            throw "Could not cancel the stuck deployment run. Review $($run.url)."
        }
        & gh run rerun $run.databaseId --repo $config.Repository
        if ($LASTEXITCODE -ne 0) {
            Start-Process $run.url
            throw "Could not retry the stuck deployment run. Review $($run.url)."
        }
        $run = $null
        for ($attempt = 0; $attempt -lt 30 -and -not $run; $attempt++) {
            Start-Sleep -Seconds 2
            $run = Get-DeploymentRun
        }
        if (-not $run) { throw "The deployment retry did not appear in GitHub Actions." }
        $result = Wait-ForDeploymentRun -Run $run
    }

    $runUrl = "https://github.com/$($config.Repository)/actions/runs/$($run.databaseId)"
    if ($result.status -ne 'completed') {
        Start-Process $runUrl
        throw "Deployment is still queued after the automatic retry. Review $runUrl."
    }
    if ($result.conclusion -ne 'success') {
        & gh run view $run.databaseId --repo $config.Repository --log-failed
        Start-Process $runUrl
        throw "GitHub Actions deployment failed with conclusion '$($result.conclusion)'. Review $runUrl."
    }
}

if (-not $NoHealthCheck) {
    try {
        $response = Invoke-WebRequest -Uri $config.HealthUrl -UseBasicParsing -TimeoutSec 30
        if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 300) { throw "Health endpoint returned HTTP $($response.StatusCode)." }
    } catch {
        if ($transport -eq 'github-actions' -and $runUrl) { Start-Process $runUrl }
        throw "Remote deploy finished, but public health verification failed: $($_.Exception.Message)"
    }
}

Start-Process $config.HealthUrl.Replace('/api/v1/health', '')
Write-Host "Production deployment succeeded: $commit" -ForegroundColor Green
