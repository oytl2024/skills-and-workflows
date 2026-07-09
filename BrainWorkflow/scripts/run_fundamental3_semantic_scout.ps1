$ConfigPath = "configs/stage1_usa_d1.yaml"
$CachePath = "docs\knowledge\cache\platform_metadata_20260702_014429.json"
$DatasetId = "fundamental3"
$FieldSuffix = "_fast_d1"
$TemplateMode = "semantic"
$WorkflowStage = "discovery"
$MaxAlphas = 30
$SubmitMode = "multi"
$MultiChunkSleepSeconds = 180
$RequestTimeoutSeconds = 120
$RequestMaxRetries = 6
$RequestBaseBackoffSeconds = 5
$HumanIdea = "Fundamental3 Fast D1 semantic Scout: cashflow/assets strength minus debt/liability/investment pressure; simple Power-Pool-compatible two-field accounting logic for lower correlation"

$env:HTTPS_PROXY = ""
$env:HTTP_PROXY = ""
$env:ALL_PROXY = ""

python -m wqb.cli semantic-preview `
  --config $ConfigPath `
  --cache-path $CachePath `
  --max-alphas-per-round $MaxAlphas `
  --dataset-id $DatasetId `
  --field-suffix $FieldSuffix `
  --template-mode $TemplateMode

python -m wqb.cli run-field-batch `
  --config $ConfigPath `
  --max-alphas-per-round $MaxAlphas `
  --dataset-id $DatasetId `
  --field-suffix $FieldSuffix `
  --template-mode $TemplateMode `
  --workflow-stage $WorkflowStage `
  --human-idea $HumanIdea `
  --field-cache-path $CachePath `
  --submit-mode $SubmitMode `
  --multi-chunk-sleep-seconds $MultiChunkSleepSeconds `
  --request-timeout-seconds $RequestTimeoutSeconds `
  --request-max-retries $RequestMaxRetries `
  --request-base-backoff-seconds $RequestBaseBackoffSeconds
