#!/usr/bin/env bash
# =============================================================
# Football Clip System — Dev Management Script
# Usage: ./dev.sh [up|down|restart|status|logs]
# =============================================================
set -euo pipefail

# ── Auto-detect Node.js (nvm, homebrew, system) ──────────────
if [ -d "$HOME/.nvm/versions/node" ]; then
  NVM_NODE=$(ls -d "$HOME/.nvm/versions/node"/*/bin 2>/dev/null | sort -V | tail -1)
  if [ -n "$NVM_NODE" ]; then
    export PATH="$NVM_NODE:$PATH"
  fi
fi
# Homebrew paths
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
PID_DIR="$SCRIPT_DIR/.pids"
ENV_FILE="$SCRIPT_DIR/.env"

API_PORT=8000
WEB_PORT=5173
REDIS_PORT=6379

# ── Auto-detect correct Python (needs fastapi/rq installed) ──
detect_python() {
  for py in python3.9 python3.10 python3.11 python3.12 python3; do
    if command -v "$py" &>/dev/null; then
      if "$py" -c "import fastapi" 2>/dev/null; then
        echo "$py"
        return
      fi
    fi
  done
  echo "python3"
}
PYTHON=$(detect_python)

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${BLUE}[dev.sh]${NC} $*"; }
ok()   { echo -e "${GREEN}[✓]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
fail() { echo -e "${RED}[✗]${NC} $*"; exit 1; }

# ── Env Setup ────────────────────────────────────────────────
setup_env() {
  if [ ! -f "$ENV_FILE" ]; then
    warn ".env not found — copying from .env.example"
    cp "$SCRIPT_DIR/.env.example" "$ENV_FILE"
    warn "Please edit .env and add your API keys before running AI features"
  fi
  mkdir -p "$LOG_DIR" "$PID_DIR"
  mkdir -p "$SCRIPT_DIR/data/uploads" "$SCRIPT_DIR/data/outputs"
}

# ── Dependency Checks ─────────────────────────────────────────
check_deps() {
  log "Checking dependencies..."
  local missing=0

  for cmd in python3 node npm redis-server ffmpeg ffprobe; do
    if command -v "$cmd" &>/dev/null; then
      ok "$cmd found"
    else
      warn "$cmd NOT found"
      missing=1
    fi
  done

  # Python packages
  if python3.9 -c "import fastapi, rq, redis, sqlalchemy" 2>/dev/null || \
     python3 -c "import fastapi, rq, redis, sqlalchemy" 2>/dev/null; then
    ok "Python packages OK"
  else
    warn "Some Python packages missing — installing..."
    pip3 install -r "$SCRIPT_DIR/requirements.txt" || fail "pip install failed"
  fi

  # Node packages
  if [ ! -d "$SCRIPT_DIR/apps/web/node_modules" ]; then
    warn "Node modules missing — installing..."
    cd "$SCRIPT_DIR/apps/web" && npm install || fail "npm install failed"
    cd "$SCRIPT_DIR"
  else
    ok "Node modules OK"
  fi

  if [ "$missing" -eq 1 ]; then
    warn "Some system dependencies missing. Install them and re-run."
    warn "  macOS: brew install redis ffmpeg node"
    warn "  Linux: apt-get install redis-server ffmpeg nodejs npm"
  fi
}

# ── Port Management ───────────────────────────────────────────
kill_port() {
  local port=$1
  local pids
  pids=$(lsof -ti tcp:"$port" 2>/dev/null || true)
  if [ -n "$pids" ]; then
    warn "Killing processes on port $port: $pids"
    kill -9 $pids 2>/dev/null || true
    sleep 0.5
  fi
}

# ── Service Start ─────────────────────────────────────────────
start_redis() {
  if redis-cli ping &>/dev/null 2>&1; then
    ok "Redis already running"
    return
  fi
  kill_port $REDIS_PORT
  log "Starting Redis on port $REDIS_PORT..."
  redis-server --port "$REDIS_PORT" --daemonize yes \
    --logfile "$LOG_DIR/redis.log" \
    --pidfile "$PID_DIR/redis.pid"
  sleep 1
  if redis-cli ping &>/dev/null; then
    ok "Redis started"
  else
    fail "Redis failed to start — check $LOG_DIR/redis.log"
  fi
}

start_api() {
  kill_port $API_PORT
  log "Starting FastAPI on port $API_PORT (Python: $PYTHON)..."
  cd "$SCRIPT_DIR"
  PYTHONPATH="$SCRIPT_DIR" \
    "$PYTHON" -m uvicorn apps.api.main:app \
    --host 0.0.0.0 --port "$API_PORT" \
    --reload \
    > "$LOG_DIR/api.log" 2>&1 &
  echo $! > "$PID_DIR/api.pid"
  sleep 2
  if curl -sf "http://localhost:$API_PORT/api/health" >/dev/null 2>&1; then
    ok "API running at http://localhost:$API_PORT"
  else
    warn "API may still be starting — check $LOG_DIR/api.log"
  fi
}

start_worker() {
  log "Starting Worker..."
  cd "$SCRIPT_DIR"
  PYTHONPATH="$SCRIPT_DIR" \
    "$PYTHON" apps/worker/main.py \
    > "$LOG_DIR/worker.log" 2>&1 &
  echo $! > "$PID_DIR/worker.pid"
  ok "Worker started (PID: $!)"
}

start_web() {
  kill_port $WEB_PORT
  log "Starting Vite dev server on port $WEB_PORT..."
  cd "$SCRIPT_DIR/apps/web"
  npm run dev \
    > "$LOG_DIR/web.log" 2>&1 &
  echo $! > "$PID_DIR/web.pid"
  sleep 3
  ok "Web started at http://localhost:$WEB_PORT"
  cd "$SCRIPT_DIR"
}

# ── Service Stop ──────────────────────────────────────────────
stop_service() {
  local name=$1
  local pid_file="$PID_DIR/$name.pid"
  if [ -f "$pid_file" ]; then
    local pid
    pid=$(cat "$pid_file")
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      ok "Stopped $name (PID $pid)"
    fi
    rm -f "$pid_file"
  fi
}

stop_redis() {
  if [ -f "$PID_DIR/redis.pid" ]; then
    redis-cli shutdown nosave 2>/dev/null || true
    rm -f "$PID_DIR/redis.pid"
    ok "Stopped Redis"
  fi
}

# ── Status ────────────────────────────────────────────────────
show_status() {
  echo ""
  echo -e "${CYAN}═══════════════════════════════════════${NC}"
  echo -e "${CYAN}  Football Clip System — Service Status${NC}"
  echo -e "${CYAN}═══════════════════════════════════════${NC}"

  check_service "Redis" "$PID_DIR/redis.pid" "redis-cli ping"
  check_service "API" "$PID_DIR/api.pid" "curl -sf http://localhost:$API_PORT/api/health"
  check_service "Worker" "$PID_DIR/worker.pid" ""
  check_service "Web" "$PID_DIR/web.pid" "curl -sf http://localhost:$WEB_PORT"

  echo ""
  echo -e "  ${BLUE}Logs:${NC}   $LOG_DIR/"
  echo -e "  ${BLUE}API:${NC}    http://localhost:$API_PORT/api/docs"
  echo -e "  ${BLUE}Web:${NC}    http://localhost:$WEB_PORT"
  echo ""
}

check_service() {
  local name=$1 pid_file=$2 health_cmd=$3
  local status="${RED}STOPPED${NC}"

  if [ -f "$pid_file" ]; then
    local pid; pid=$(cat "$pid_file")
    if kill -0 "$pid" 2>/dev/null; then
      if [ -z "$health_cmd" ] || eval "$health_cmd" &>/dev/null; then
        status="${GREEN}RUNNING${NC} (PID $pid)"
      else
        status="${YELLOW}STARTING${NC} (PID $pid)"
      fi
    fi
  elif [ "$name" = "Redis" ] && redis-cli ping &>/dev/null 2>&1; then
    status="${GREEN}RUNNING${NC} (external)"
  fi

  printf "  %-10s %b\n" "$name" "$status"
}

# ── Commands ──────────────────────────────────────────────────
cmd_up() {
  echo ""
  echo -e "${CYAN}Starting Football Clip System...${NC}"
  setup_env
  check_deps
  start_redis
  start_api
  start_worker
  start_web
  show_status
}

cmd_down() {
  echo ""
  log "Stopping all services..."
  stop_service "web"
  stop_service "worker"
  stop_service "api"
  stop_redis
  ok "All services stopped"
}

cmd_restart() {
  cmd_down
  sleep 1
  cmd_up
}

cmd_logs() {
  local svc=${1:-"api"}
  local log_file="$LOG_DIR/$svc.log"
  if [ -f "$log_file" ]; then
    tail -f "$log_file"
  else
    warn "No log file found: $log_file"
    ls "$LOG_DIR/" 2>/dev/null || warn "Log directory empty"
  fi
}

# ── Entry Point ───────────────────────────────────────────────
case "${1:-up}" in
  up)      cmd_up ;;
  down)    cmd_down ;;
  restart) cmd_restart ;;
  status)  setup_env; show_status ;;
  logs)    cmd_logs "${2:-api}" ;;
  *)
    echo "Usage: $0 [up|down|restart|status|logs [service]]"
    echo "  Services for logs: api, worker, web, redis"
    exit 1
    ;;
esac
