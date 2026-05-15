#!/usr/bin/env bash
# Auto-detect Python, kill stale worker processes, then start RQ worker.
# Running the worker directly is more reliable inside Docker/Linux than
# delegating to the watchfiles CLI with a nested shell command.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEFAULT_VENV_PY="${PYTHON_VENV_DIR:-$ROOT/.venv}/bin/python"
PYTHON_BIN="$DEFAULT_VENV_PY"
if ! [ -x "$PYTHON_BIN" ] || ! "$PYTHON_BIN" -c "import rq" >/dev/null 2>&1; then
  PYTHON_BIN="$(bash "$ROOT/scripts/ensure-python-env.sh" rq watchfiles)"
fi

if [ -z "$PYTHON_BIN" ] || ! [ -x "$PYTHON_BIN" ]; then
  echo "ERROR: Unable to resolve a Python interpreter with worker dependencies installed." >&2
  exit 1
fi

# Kill any stale worker processes (rq worker on this queue)
pkill -f "apps/worker/main.py" 2>/dev/null || true
sleep 0.3

exec env PYTHONPATH="$ROOT" "$PYTHON_BIN" "$ROOT/apps/worker/main.py"
