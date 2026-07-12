#!/usr/bin/env bash
set -euo pipefail

CONFIG_PATH="configs/stage1_usa_d1.yaml"
RUN_DIR="runs/20260703_023244"
SUBMIT_MODE="serial"
REQUEST_TIMEOUT_SECONDS="120"
REQUEST_MAX_RETRIES="6"
REQUEST_BASE_BACKOFF_SECONDS="5"

export HTTPS_PROXY=""
export HTTP_PROXY=""
export ALL_PROXY=""

python -m wqb.cli retry-planned \
  --config "$CONFIG_PATH" \
  --run-dir "$RUN_DIR" \
  --submit-mode "$SUBMIT_MODE" \
  --request-timeout-seconds "$REQUEST_TIMEOUT_SECONDS" \
  --request-max-retries "$REQUEST_MAX_RETRIES" \
  --request-base-backoff-seconds "$REQUEST_BASE_BACKOFF_SECONDS"

python -m wqb.cli status --config "$CONFIG_PATH" --run-dir "$RUN_DIR"
