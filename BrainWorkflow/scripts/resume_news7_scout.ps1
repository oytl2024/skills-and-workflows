$ConfigPath = "configs/stage1_usa_d1.yaml"
$RunDir = "runs\20260703_023244"
$SubmitMode = "serial"
$RequestTimeoutSeconds = 120
$RequestMaxRetries = 6
$RequestBaseBackoffSeconds = 5

$env:HTTPS_PROXY = ""
$env:HTTP_PROXY = ""
$env:ALL_PROXY = ""

python -m wqb.cli retry-planned `
  --config $ConfigPath `
  --run-dir $RunDir `
  --submit-mode $SubmitMode `
  --request-timeout-seconds $RequestTimeoutSeconds `
  --request-max-retries $RequestMaxRetries `
  --request-base-backoff-seconds $RequestBaseBackoffSeconds

python -m wqb.cli status --config $ConfigPath --run-dir $RunDir
