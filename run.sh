#!/usr/bin/env bash
# Single entrypoint: sets up (if needed) and runs the whole project as a
# background service — like `systemctl start/stop/restart/status`, but
# without needing systemd (this runs on macOS too). The worker and API each
# run under their own restart-on-crash supervisor loop (systemd's
# `Restart=always`), detached from the terminal, logging to backend/logs/.
#
# Usage:
#   ./run.sh [start]   set up if needed, then start both services in the
#                       background (safe to re-run — a no-op if already up)
#   ./run.sh stop       stop both services
#   ./run.sh restart    stop, then start
#   ./run.sh status     show whether each service is running
#   ./run.sh logs       tail -f both log files
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
VENV_DIR="$BACKEND_DIR/.venv"
PID_DIR="$BACKEND_DIR/.run"
LOG_DIR="$BACKEND_DIR/logs"
SERVICES=(worker api)

mkdir -p "$PID_DIR" "$LOG_DIR"

is_running() {
  local pid_file="$PID_DIR/$1.pid"
  [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null
}

# Runs "$@" in a restart-on-crash loop (systemd's Restart=always + RestartSec),
# detached from the terminal, logging to $LOG_DIR/<name>.log. The loop's own
# PID is saved so stop() can find it later.
supervise() {
  local name="$1"; shift
  local log_file="$LOG_DIR/$name.log"
  (
    while true; do
      echo "$(date -u +%FT%TZ) [$name] starting: $*" >> "$log_file"
      "$@" >> "$log_file" 2>&1 || true
      echo "$(date -u +%FT%TZ) [$name] exited, restarting in 3s..." >> "$log_file"
      sleep 3
    done
  ) < /dev/null > /dev/null 2>&1 &
  disown
  echo $! > "$PID_DIR/$name.pid"
}

stop_one() {
  local name="$1"
  local pid_file="$PID_DIR/$name.pid"
  if [ -f "$pid_file" ]; then
    local pid
    pid=$(cat "$pid_file")
    if kill -0 "$pid" 2>/dev/null; then
      pkill -P "$pid" 2>/dev/null || true   # the loop's current child (uvicorn / run_cycle)
      kill "$pid" 2>/dev/null || true       # the loop itself
    fi
    rm -f "$pid_file"
  fi
}

do_setup() {
  cd "$BACKEND_DIR"

  if [ ! -f "$VENV_DIR/bin/activate" ]; then
    echo "==> Creating virtualenv"
    python3 -m venv "$VENV_DIR"
  fi
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"

  if [ ! -f "$VENV_DIR/.deps_installed" ] || [ requirements.txt -nt "$VENV_DIR/.deps_installed" ]; then
    echo "==> Installing backend dependencies"
    pip install -q -r requirements.txt
    touch "$VENV_DIR/.deps_installed"
  fi

  if [ ! -f .env ]; then
    echo "==> No backend/.env found, copying from .env.example (fill in OLLAMA_* before real use)"
    cp "$ROOT_DIR/.env.example" .env
  fi

  echo "==> Running migrations"
  alembic upgrade head

  AGENT_COUNT=$(python -c "
from app.core.database import session_scope
from app.models.agent import Agent
from sqlalchemy import select, func
import asyncio

async def main():
    async with session_scope() as db:
        print((await db.execute(select(func.count()).select_from(Agent))).scalar())

asyncio.run(main())
")

  if [ "$AGENT_COUNT" -eq 0 ]; then
    echo "==> No agents found, bootstrapping initial population"
    python -m scripts.bootstrap_population
  fi
}

cmd_start() {
  if is_running worker || is_running api; then
    echo "Already running (use './run.sh status' or './run.sh restart')."
    exit 0
  fi

  do_setup

  echo "==> Starting trading worker (restart-on-crash, logging to $LOG_DIR/worker.log)"
  supervise worker "$VENV_DIR/bin/python" -m scripts.run_cycle

  echo "==> Starting API + frontend (restart-on-crash, logging to $LOG_DIR/api.log)"
  supervise api "$VENV_DIR/bin/uvicorn" app.main:app --host 0.0.0.0 --port 8000

  sleep 1
  cmd_status
  echo ""
  echo "Dashboard: http://localhost:8000/"
  echo "Logs:      ./run.sh logs"
  echo "Stop:      ./run.sh stop"
}

cmd_stop() {
  for name in "${SERVICES[@]}"; do
    echo "==> Stopping $name"
    stop_one "$name"
  done
}

cmd_status() {
  for name in "${SERVICES[@]}"; do
    if is_running "$name"; then
      echo "$name: running (pid $(cat "$PID_DIR/$name.pid"))"
    else
      echo "$name: stopped"
    fi
  done
}

cmd_logs() {
  tail -f "$LOG_DIR"/*.log
}

case "${1:-start}" in
  start)   cmd_start ;;
  stop)    cmd_stop ;;
  restart) cmd_stop; sleep 1; cmd_start ;;
  status)  cmd_status ;;
  logs)    cmd_logs ;;
  *)
    echo "Usage: $0 {start|stop|restart|status|logs}" >&2
    exit 1
    ;;
esac
