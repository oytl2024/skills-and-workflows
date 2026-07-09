#!/usr/bin/env bash
set -euo pipefail

MAX_ALPHAS_PER_ROUND=50
MAX_ROUNDS=5
CONFIG_PATH="configs/stage1_usa_d1.yaml"

python -m wqb.cli run-stage1 \
  --config "${CONFIG_PATH}" \
  --max-alphas-per-round "${MAX_ALPHAS_PER_ROUND}" \
  --max-rounds "${MAX_ROUNDS}"
