param(
    [string]$RunDir = "runs/20260702_102406",
    [string]$AlphaId = "3q7OQaog",
    [string]$SignalNote = "straight PnL observed by user",
    [int]$RequestTimeoutSeconds = 20,
    [int]$RequestMaxRetries = 1,
    [int]$RequestBaseBackoffSeconds = 2,
    [int]$MaxScan = 30,
    [string]$Proxy = "http://127.0.0.1:7890"
)

$ErrorActionPreference = "Stop"

$env:HTTPS_PROXY = $Proxy
$env:HTTP_PROXY = $Proxy

Write-Host "Inspecting benchmark alpha $AlphaId"
python -m wqb.cli inspect-alpha `
    --alpha-id $AlphaId `
    --run-dir $RunDir `
    --signal-note $SignalNote `
    --request-timeout-seconds $RequestTimeoutSeconds `
    --request-max-retries $RequestMaxRetries `
    --request-base-backoff-seconds $RequestBaseBackoffSeconds

Write-Host "Recovering in-flight simulations from $RunDir"
python -m wqb.cli complete-in-flight `
    --run-dir $RunDir `
    --request-timeout-seconds $RequestTimeoutSeconds `
    --request-max-retries $RequestMaxRetries `
    --request-base-backoff-seconds $RequestBaseBackoffSeconds

Write-Host "Scanning recent existing IS alphas as read-only recovery"
python -m wqb.cli scan-existing `
    --run-dir $RunDir `
    --max-scan $MaxScan `
    --request-timeout-seconds $RequestTimeoutSeconds `
    --request-max-retries $RequestMaxRetries `
    --request-base-backoff-seconds $RequestBaseBackoffSeconds

Write-Host "Local status after recovery attempts"
python -m wqb.cli status --run-dir $RunDir
