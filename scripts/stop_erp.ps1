$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$port = if ($env:ERP_API_PORT) { [int]$env:ERP_API_PORT } else { 8000 }

function Get-AncestorProcessIds {
    param(
        [int]$ProcessId,
        [object[]]$AllProcesses
    )

    $ancestors = [System.Collections.Generic.HashSet[int]]::new()
    $current = $AllProcesses | Where-Object { $_.ProcessId -eq $ProcessId } | Select-Object -First 1
    while ($current -and $current.ParentProcessId) {
        $parentId = [int]$current.ParentProcessId
        if (-not $ancestors.Add($parentId)) {
            break
        }
        $current = $AllProcesses | Where-Object { $_.ProcessId -eq $parentId } | Select-Object -First 1
    }

    return @($ancestors | ForEach-Object { $_ })
}

function Get-DescendantProcessIds {
    param(
        [int[]]$ParentIds,
        [object[]]$AllProcesses
    )

    $seen = [System.Collections.Generic.HashSet[int]]::new()
    $frontier = @($ParentIds | Where-Object { $_ -and $_ -ne $PID } | Select-Object -Unique)
    while ($frontier.Count -gt 0) {
        $next = @()
        foreach ($parentId in $frontier) {
            $children = @($AllProcesses | Where-Object { $_.ParentProcessId -eq $parentId })
            foreach ($child in $children) {
                if ($child.ProcessId -ne $PID -and $seen.Add([int]$child.ProcessId)) {
                    $next += [int]$child.ProcessId
                }
            }
        }
        $frontier = @($next | Select-Object -Unique)
    }

    return @($seen)
}

$allProcesses = @(Get-CimInstance Win32_Process)
$protectedIds = @($PID) + @(Get-AncestorProcessIds -ProcessId $PID -AllProcesses $allProcesses)
$escapedRoot = [regex]::Escape((Resolve-Path -LiteralPath $repoRoot).Path.TrimEnd("\"))
$launcherPattern = $escapedRoot + "\\(RUN_ERP\.bat|scripts\\run_(pc_local|api|desktop)\.ps1)"

$matchedProcessIds = @(
    $allProcesses |
        Where-Object {
            $_.ProcessId -notin $protectedIds -and
            $_.CommandLine -and (
                $_.CommandLine -match 'erp\.apps\.(api|worker|desktop)' -or
                $_.CommandLine -match $launcherPattern -or
                ($_.CommandLine -like ('*' + $repoRoot + '*') -and $_.CommandLine -match 'multiprocessing\.spawn') -or
                ($_.CommandLine -like ('*' + $repoRoot + '*') -and $_.CommandLine -match '(node|npm|next)')
            )
        } |
        Select-Object -ExpandProperty ProcessId
)

$listenerIds = @(
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique |
        Where-Object { $_ -gt 0 -and $_ -notin $protectedIds }
)

$baseIds = @($matchedProcessIds + $listenerIds) | Where-Object { $_ } | Select-Object -Unique
$childIds = @(Get-DescendantProcessIds -ParentIds $baseIds -AllProcesses $allProcesses)
$processIds = @($childIds + $baseIds) |
    Where-Object { $_ -and $_ -notin $protectedIds } |
    Select-Object -Unique

if (-not $processIds) {
    Write-Host "No ERP Python processes found."
    exit 0
}

foreach ($processId in $processIds) {
    try {
        if (-not (Get-Process -Id $processId -ErrorAction SilentlyContinue)) {
            continue
        }
        Stop-Process -Id $processId -Force -ErrorAction Stop
        Write-Host "Stopped ERP process $processId"
        Start-Sleep -Milliseconds 150
    }
    catch {
        Write-Host "Could not stop ERP process ${processId}: $($_.Exception.Message)"
    }
}
