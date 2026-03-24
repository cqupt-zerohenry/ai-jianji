#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="${PYTHON_VENV_DIR:-$ROOT/.venv}"
LOCK_DIR="$ROOT/.venv-install.lock"
REQUIREMENTS_FILE="$ROOT/requirements.txt"
STAMP_FILE="$VENV_DIR/.requirements-installed"

# Homebrew Python is commonly installed outside the default PATH in non-interactive shells.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

python_has_modules() {
  local py="$1"
  shift || true

  if [ ! -x "$py" ]; then
    return 1
  fi

  if [ "$#" -eq 0 ]; then
    return 0
  fi

  local imports=""
  local module=""
  for module in "$@"; do
    if [ -n "$imports" ]; then
      imports="$imports, "
    fi
    imports="$imports$module"
  done

  "$py" -c "import $imports" >/dev/null 2>&1
}

find_base_python() {
  local py=""

  for py in python3.12 python3.11 python3.10 python3.9 python3 "$HOME/.pyenv/shims/python3"; do
    if command -v "$py" >/dev/null 2>&1; then
      command -v "$py"
      return 0
    fi
  done

  local framework_py=""
  shopt -s nullglob
  for framework_py in /Library/Frameworks/Python.framework/Versions/3.*/bin/python3.*; do
    if [ -x "$framework_py" ]; then
      echo "$framework_py"
      shopt -u nullglob
      return 0
    fi
  done
  shopt -u nullglob

  return 1
}

requirements_need_install() {
  if [ ! -f "$STAMP_FILE" ]; then
    return 0
  fi

  [ "$REQUIREMENTS_FILE" -nt "$STAMP_FILE" ]
}

cleanup_stale_lock() {
  if [ ! -d "$LOCK_DIR" ]; then
    return 0
  fi

  if [ ! -f "$LOCK_DIR/pid" ]; then
    rm -rf "$LOCK_DIR"
    return 0
  fi

  local pid=""
  pid="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
  if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
    rm -rf "$LOCK_DIR"
  fi
}

acquire_lock() {
  local waited=0

  while ! mkdir "$LOCK_DIR" 2>/dev/null; do
    cleanup_stale_lock
    if mkdir "$LOCK_DIR" 2>/dev/null; then
      break
    fi

    if [ "$waited" -ge 300 ]; then
      echo "ERROR: Timed out waiting for Python environment setup to finish." >&2
      exit 1
    fi

    sleep 1
    waited=$((waited + 1))
  done

  echo "$$" > "$LOCK_DIR/pid"
  trap 'rm -rf "$LOCK_DIR"' EXIT
}

main() {
  local required_modules=("$@")
  local venv_python="$VENV_DIR/bin/python"

  if [ -x "$venv_python" ] && ! requirements_need_install && python_has_modules "$venv_python" "${required_modules[@]}"; then
    echo "$venv_python"
    return 0
  fi

  local base_python=""
  base_python="$(find_base_python || true)"
  if [ -z "$base_python" ]; then
    echo "ERROR: No python3 interpreter found. Install Python 3 first." >&2
    exit 1
  fi

  acquire_lock

  if [ -x "$venv_python" ] && ! requirements_need_install && python_has_modules "$venv_python" "${required_modules[@]}"; then
    echo "$venv_python"
    return 0
  fi

  if [ ! -x "$venv_python" ]; then
    echo "[python-env] Creating virtual environment at $VENV_DIR" >&2
    "$base_python" -m venv "$VENV_DIR"
  fi

  "$venv_python" -m ensurepip --upgrade >/dev/null 2>&1 || true

  if requirements_need_install || ! python_has_modules "$venv_python" "${required_modules[@]}"; then
    echo "[python-env] Installing Python dependencies from requirements.txt" >&2
    "$venv_python" -m pip install -r "$REQUIREMENTS_FILE"
    touch "$STAMP_FILE"
  fi

  if ! python_has_modules "$venv_python" "${required_modules[@]}"; then
    echo "ERROR: Python environment is missing required modules: ${required_modules[*]}" >&2
    exit 1
  fi

  echo "$venv_python"
}

main "$@"
