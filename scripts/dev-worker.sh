#!/usr/bin/env bash
# Auto-detect Python, kill stale worker processes, then start RQ worker
# with watchfiles for hot reload.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Kill any stale worker processes (rq worker on this queue)
pkill -f "apps/worker/main.py" 2>/dev/null || true
sleep 0.3

for py in \
  /Library/Frameworks/Python.framework/Versions/3.*/bin/python3.* \
  "$HOME/.pyenv/shims/python3" \
  python3.12 python3.11 python3.10 python3.9 python3
do
  if command -v "$py" &>/dev/null 2>&1 && "$py" -c "import rq" 2>/dev/null; then
    exec env PYTHONPATH="$ROOT" "$py" -m watchfiles \
      --filter python \
      "env PYTHONPATH=$ROOT $py $ROOT/apps/worker/main.py" \
      "$ROOT/apps/worker" "$ROOT/apps/api"
  fi
done

echo "ERROR: No Python with rq found. Run: pip3 install -r requirements.txt" >&2
exit 1
