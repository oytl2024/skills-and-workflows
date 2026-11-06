#!/usr/bin/env bash
set -euo pipefail
# Input: explicit offline JSON and output options. Output: developer artifacts only, never live research.
PYTHON="${PYTHON:-python}"
MAX_MECHANISMS="${MAX_MECHANISMS:-3}"
MAX_CONDITIONS_PER_MECHANISM="${MAX_CONDITIONS_PER_MECHANISM:-2}"
cd "$(dirname "$0")/.."
exec "$PYTHON" -m scripts.demo_hypothesis_design \
  --max-mechanisms "$MAX_MECHANISMS" \
  --max-conditions-per-mechanism "$MAX_CONDITIONS_PER_MECHANISM" "$@"
