#!/usr/bin/env bash
set -euo pipefail
# Input: CLI options. Output: JSON result and exit code. Explicit maintenance only.
PYTHON="${PYTHON:-python}"
MAX_MECHANISMS="${MAX_MECHANISMS:-3}"
MAX_CONDITIONS_PER_MECHANISM="${MAX_CONDITIONS_PER_MECHANISM:-2}"
cd "$(dirname "$0")/.."
exec "$PYTHON" -m wqb.cli compile-semantic-knowledge \
  --max-mechanisms "$MAX_MECHANISMS" \
  --max-conditions-per-mechanism "$MAX_CONDITIONS_PER_MECHANISM" "$@"
