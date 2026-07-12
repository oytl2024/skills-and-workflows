$ErrorActionPreference = "Stop"

$MaxAlphasPerRound = 50
$MaxRounds = 5
$ConfigPath = "configs/stage1_usa_d1.yaml"

python -m wqb.cli run-stage1 `
  --config $ConfigPath `
  --max-alphas-per-round $MaxAlphasPerRound `
  --max-rounds $MaxRounds
