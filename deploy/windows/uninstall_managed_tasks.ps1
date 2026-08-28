param(
    [string]$ApiTaskName = "ChoiceOye ERP API",
    [string]$WorkerTaskName = "ChoiceOye ERP Worker"
)

$ErrorActionPreference = "Stop"

foreach ($taskName in @($ApiTaskName, $WorkerTaskName)) {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($null -ne $task) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Host "Removed scheduled task: $taskName"
    }
}
