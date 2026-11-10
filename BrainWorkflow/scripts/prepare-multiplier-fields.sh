#!/usr/bin/env bash
# Explicit maintenance only. Scope and reduced bounds remain fixed for this job.
set -euo pipefail
PYTHON="${PYTHON:-python}"
KNOWLEDGE_ROOT="${KNOWLEDGE_ROOT:?Set KNOWLEDGE_ROOT}"
JOB_DIR="${JOB_DIR:?Set a dedicated JOB_DIR}"
REGION="${REGION:?Set REGION}"
DELAY="${DELAY:?Set DELAY}"
UNIVERSE="${UNIVERSE:?Set UNIVERSE}"
MAX_TRANSPORT_ATTEMPTS="${MAX_TRANSPORT_ATTEMPTS:-24}"
TOTAL_SECONDS="${TOTAL_SECONDS:-300}"
REQUEST_TIMEOUT_SECONDS="${REQUEST_TIMEOUT_SECONDS:-12}"
MAX_FIELDS="${MAX_FIELDS:-100}"
MAX_DATASETS="${MAX_DATASETS:-2}"
MAX_FIELDS_PER_DATASET="${MAX_FIELDS_PER_DATASET:-50}"
MAX_RETRIES=0
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
exec "$PYTHON" -B -m wqb.multiplier_preparation \
  --knowledge-root "$KNOWLEDGE_ROOT" --job-dir "$JOB_DIR" \
  --region "$REGION" --delay "$DELAY" --universe "$UNIVERSE" \
  --request-limit "$MAX_TRANSPORT_ATTEMPTS" --total-seconds "$TOTAL_SECONDS" \
  --request-timeout-seconds "$REQUEST_TIMEOUT_SECONDS" --max-fields "$MAX_FIELDS" \
  --max-datasets "$MAX_DATASETS" --max-fields-per-dataset "$MAX_FIELDS_PER_DATASET" \
  --max-retries "$MAX_RETRIES"
