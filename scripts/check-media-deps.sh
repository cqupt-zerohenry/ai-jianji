#!/usr/bin/env bash
# Fail fast if ffmpeg/ffprobe are unavailable before starting dev services.
set -euo pipefail

# Common Homebrew locations are not always in non-interactive shell PATH.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

find_bin() {
  local name="$1"
  if command -v "$name" >/dev/null 2>&1; then
    command -v "$name"
    return 0
  fi

  for dir in /opt/homebrew/bin /usr/local/bin /usr/bin /bin; do
    if [ -x "$dir/$name" ]; then
      echo "$dir/$name"
      return 0
    fi
  done
  return 1
}

FFMPEG_BIN="$(find_bin ffmpeg || true)"
FFPROBE_BIN="$(find_bin ffprobe || true)"

if [ -z "$FFMPEG_BIN" ] || [ -z "$FFPROBE_BIN" ]; then
  echo "ERROR: Missing required media tools." >&2
  echo "Required: ffmpeg and ffprobe" >&2
  echo "macOS install: brew install ffmpeg" >&2
  echo "Ubuntu/Debian install: sudo apt-get install -y ffmpeg" >&2
  exit 1
fi

# Ensure binaries are executable and healthy.
"$FFMPEG_BIN" -version >/dev/null 2>&1 || {
  echo "ERROR: ffmpeg is present but failed to execute: $FFMPEG_BIN" >&2
  exit 1
}
"$FFPROBE_BIN" -version >/dev/null 2>&1 || {
  echo "ERROR: ffprobe is present but failed to execute: $FFPROBE_BIN" >&2
  exit 1
}

echo "[deps] ffmpeg:  $FFMPEG_BIN"
echo "[deps] ffprobe: $FFPROBE_BIN"

REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
REDIS_CLI_BIN="$(find_bin redis-cli || true)"

if [ -z "$REDIS_CLI_BIN" ]; then
  echo "ERROR: redis-cli not found. Please install Redis tools first." >&2
  echo "macOS install: brew install redis" >&2
  exit 1
fi

if ! "$REDIS_CLI_BIN" -u "$REDIS_URL" ping >/dev/null 2>&1; then
  echo "[deps] Redis not reachable at $REDIS_URL"
  if [[ "$REDIS_URL" == redis://localhost* ]] || [[ "$REDIS_URL" == redis://127.0.0.1* ]]; then
    REDIS_SERVER_BIN="$(find_bin redis-server || true)"
    if [ -z "$REDIS_SERVER_BIN" ]; then
      echo "ERROR: redis-server not found. Install with: brew install redis" >&2
      exit 1
    fi
    echo "[deps] Starting local Redis..."
    "$REDIS_SERVER_BIN" --daemonize yes >/dev/null 2>&1 || true
    sleep 0.8
  fi
fi

if ! "$REDIS_CLI_BIN" -u "$REDIS_URL" ping >/dev/null 2>&1; then
  echo "ERROR: Redis is not available at $REDIS_URL" >&2
  echo "Please start Redis and retry." >&2
  exit 1
fi

echo "[deps] redis:  $REDIS_URL (ok)"
