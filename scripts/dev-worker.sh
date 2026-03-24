#!/usr/bin/env bash
# Auto-detect Python, kill stale worker processes, then start RQ worker
# with watchfiles for hot reload.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="$(bash "$ROOT/scripts/ensure-python-env.sh" rq watchfiles)"

# Kill any stale worker processes (rq worker on this queue)
pkill -f "apps/worker/main.py" 2>/dev/null || true
sleep 0.3

exec env PYTHONPATH="$ROOT" "$PYTHON_BIN" -m watchfiles \
  --filter python \
  "env PYTHONPATH=$ROOT $PYTHON_BIN $ROOT/apps/worker/main.py" \
  "$ROOT/apps/worker" "$ROOT/apps/api"
