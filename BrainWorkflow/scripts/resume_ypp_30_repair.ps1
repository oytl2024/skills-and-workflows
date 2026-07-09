$ErrorActionPreference = "Stop"

$ExpressionFile = "research_batches\20260702_ypp_30_repair.jsonl"
$RunDir = "runs\20260702_ypp_30_repair"
$RequestTimeoutSeconds = 120
$RequestMaxRetries = 6
$RequestBaseBackoffSeconds = 5
$MultiChunkSleepSeconds = 600

$env:HTTPS_PROXY = ""
$env:HTTP_PROXY = ""
$env:ALL_PROXY = ""

python -m wqb.cli run-expression-file `
  --expression-file $ExpressionFile `
  --run-dir $RunDir `
  --submit-mode multi `
  --multi-chunk-sleep-seconds $MultiChunkSleepSeconds `
  --request-timeout-seconds $RequestTimeoutSeconds `
  --request-max-retries $RequestMaxRetries `
  --request-base-backoff-seconds $RequestBaseBackoffSeconds

python -m wqb.cli status --run-dir $RunDir
