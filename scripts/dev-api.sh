#!/usr/bin/env bash
# Auto-detect Python with fastapi installed, clear stale API/reloader processes,
# then start uvicorn with --reload.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${API_PORT:-8000}"
HOST="${API_HOST:-0.0.0.0}"
PID_FILE="$ROOT/.pids/api.pid"

cleanup_api_processes() {
  local existing=""

  # Stop process tracked by pid file from dev.sh (if present).
  if [ -f "$PID_FILE" ]; then
    local api_pid=""
    api_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [ -n "$api_pid" ]; then
      kill "$api_pid" 2>/dev/null || true
      sleep 0.2
      kill -9 "$api_pid" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
  fi

  # Stop uvicorn reloader parents that may not hold the port but can respawn
  # child workers, creating a race on startup.
  if command -v pkill >/dev/null 2>&1; then
    pkill -f "uvicorn apps.api.main:app" 2>/dev/null || true
    pkill -f "apps.api.main:app" 2>/dev/null || true
  fi

  existing="$(lsof -ti "tcp:$PORT" 2>/dev/null || true)"
  if [ -n "$existing" ]; then
    echo "[dev-api] Port $PORT in use (PID $existing) - terminating..."
    kill $existing 2>/dev/null || true
    sleep 0.6
  fi

  existing="$(lsof -ti "tcp:$PORT" 2>/dev/null || true)"
  if [ -n "$existing" ]; then
    echo "[dev-api] Port $PORT still busy (PID $existing) - forcing kill..."
    kill -9 $existing 2>/dev/null || true
    sleep 0.4
  fi

  existing="$(lsof -ti "tcp:$PORT" 2>/dev/null || true)"
  if [ -n "$existing" ]; then
    echo "ERROR: Port $PORT is still in use (PID $existing)." >&2
    echo "Try: lsof -nP -iTCP:$PORT -sTCP:LISTEN" >&2
    exit 1
  fi
}

PYTHON_BIN="$(bash "$ROOT/scripts/ensure-python-env.sh" fastapi uvicorn)"

if [ "${1:-}" = "--version" ]; then
  exec "$PYTHON_BIN" -m uvicorn --version
fi

cleanup_api_processes
exec env PYTHONPATH="$ROOT" "$PYTHON_BIN" -m uvicorn apps.api.main:app \
  --host "$HOST" --port "$PORT" \
  --reload --reload-dir "$ROOT/apps/api"
