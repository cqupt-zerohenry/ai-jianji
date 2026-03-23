#!/usr/bin/env bash
# Keep web dev server on a stable port by clearing stale listeners first.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${WEB_PORT:-5173}"
PID_FILE="$ROOT/.pids/web.pid"

cleanup_web_processes() {
  local existing=""

  if [ -f "$PID_FILE" ]; then
    local web_pid=""
    web_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [ -n "$web_pid" ]; then
      kill "$web_pid" 2>/dev/null || true
      sleep 0.2
      kill -9 "$web_pid" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
  fi

  existing="$(lsof -ti "tcp:$PORT" 2>/dev/null || true)"
  if [ -n "$existing" ]; then
    echo "[dev-web] Port $PORT in use (PID $existing) - terminating..."
    kill $existing 2>/dev/null || true
    sleep 0.6
  fi

  existing="$(lsof -ti "tcp:$PORT" 2>/dev/null || true)"
  if [ -n "$existing" ]; then
    echo "[dev-web] Port $PORT still busy (PID $existing) - forcing kill..."
    kill -9 $existing 2>/dev/null || true
    sleep 0.4
  fi

  existing="$(lsof -ti "tcp:$PORT" 2>/dev/null || true)"
  if [ -n "$existing" ]; then
    echo "[dev-web] Port $PORT is still in use (PID $existing)." >&2
    echo "[dev-web] Continuing startup and letting Vite choose the next free port." >&2
  fi
}

cleanup_web_processes
exec pnpm --filter web dev
