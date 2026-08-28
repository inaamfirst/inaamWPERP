param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [Parameter(Mandatory = $true)]
    [string]$Token
)

$ErrorActionPreference = "Stop"

$headers = @{ Authorization = "Bearer $Token" }
Invoke-RestMethod `
    -Method Post `
    -Uri "$BaseUrl/api/v1/backup/sqlite" `
    -Headers $headers
