#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="$(bash "$ROOT/scripts/ensure-python-env.sh" pytest)"

exec env PYTHONPATH="$ROOT" "$PYTHON_BIN" -m pytest apps/api/tests/ -v "$@"
