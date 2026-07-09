#!/usr/bin/env bash
set -euo pipefail

# Input: environment variables CONFIG, PROXY_URL, and MAX_SCAN. Output: run artifacts in runs/.
# Function: execute the current Stage 1 loop queue without hardcoding credentials.

CONFIG="${CONFIG:-configs/stage1_usa_d1.yaml}"
PROXY_URL="${PROXY_URL:-http://127.0.0.1:7890}"
MAX_SCAN="${MAX_SCAN:-80}"

export HTTP_PROXY="${HTTP_PROXY:-$PROXY_URL}"
export HTTPS_PROXY="${HTTPS_PROXY:-$PROXY_URL}"
export ALL_PROXY="${ALL_PROXY:-$PROXY_URL}"

python -m wqb.cli complete-in-flight --config "$CONFIG" --run-dir runs/20260701_122157 || true
python -m wqb.cli complete-in-flight --config "$CONFIG" --run-dir runs/20260701_130847 || true
python -m wqb.cli complete-in-flight --config "$CONFIG" --run-dir runs/20260701_133506 || true
python -m wqb.cli complete-in-flight --config "$CONFIG" --run-dir runs/20260701_114825 || true

python -m wqb.cli status --config "$CONFIG" --run-dir runs/20260701_122157
python -m wqb.cli status --config "$CONFIG" --run-dir runs/20260701_130847
python -m wqb.cli status --config "$CONFIG" --run-dir runs/20260701_133506

python -m wqb.cli scan-existing --config "$CONFIG" --max-scan "$MAX_SCAN" || true
