#!/usr/bin/env bash
set -euo pipefail

CONFIG_PATH="configs/stage1_usa_d1.yaml"
CACHE_PATH="docs/knowledge/cache/platform_metadata_20260702_014429.json"
DATASET_ID="fundamental3"
FIELD_SUFFIX="_fast_d1"
TEMPLATE_MODE="semantic"
WORKFLOW_STAGE="discovery"
MAX_ALPHAS="30"
SUBMIT_MODE="multi"
MULTI_CHUNK_SLEEP_SECONDS="180"
REQUEST_TIMEOUT_SECONDS="120"
REQUEST_MAX_RETRIES="6"
REQUEST_BASE_BACKOFF_SECONDS="5"
HUMAN_IDEA="Fundamental3 Fast D1 semantic Scout: cashflow/assets strength minus debt/liability/investment pressure; simple Power-Pool-compatible two-field accounting logic for lower correlation"

export HTTPS_PROXY=""
export HTTP_PROXY=""
export ALL_PROXY=""

python -m wqb.cli semantic-preview \
  --config "$CONFIG_PATH" \
  --cache-path "$CACHE_PATH" \
  --max-alphas-per-round "$MAX_ALPHAS" \
  --dataset-id "$DATASET_ID" \
  --field-suffix "$FIELD_SUFFIX" \
  --template-mode "$TEMPLATE_MODE"

python -m wqb.cli run-field-batch \
  --config "$CONFIG_PATH" \
  --max-alphas-per-round "$MAX_ALPHAS" \
  --dataset-id "$DATASET_ID" \
  --field-suffix "$FIELD_SUFFIX" \
  --template-mode "$TEMPLATE_MODE" \
  --workflow-stage "$WORKFLOW_STAGE" \
  --human-idea "$HUMAN_IDEA" \
  --field-cache-path "$CACHE_PATH" \
  --submit-mode "$SUBMIT_MODE" \
  --multi-chunk-sleep-seconds "$MULTI_CHUNK_SLEEP_SECONDS" \
  --request-timeout-seconds "$REQUEST_TIMEOUT_SECONDS" \
  --request-max-retries "$REQUEST_MAX_RETRIES" \
  --request-base-backoff-seconds "$REQUEST_BASE_BACKOFF_SECONDS"
