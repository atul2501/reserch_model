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
#   ./run.sh backup     pg_dump the database to backend/data/backups/, prints
#                       the resulting file's path (last line: BACKUP_PATH=...)
#                       so it's easy to scp off the machine, e.g.:
#                         scp -i key.pem ec2-user@host:"$(ssh -i key.pem ec2-user@host './run.sh backup' | tail -1 | cut -d= -f2)" .
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
VENV_DIR="$BACKEND_DIR/.venv"
PID_DIR="$BACKEND_DIR/.run"
LOG_DIR="$BACKEND_DIR/logs"
BACKUP_DIR="$BACKEND_DIR/data/backups"
SERVICES=(worker research api analytics)

mkdir -p "$PID_DIR" "$LOG_DIR"

is_running() {
  local pid_file="$PID_DIR/$1.pid"
  [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null
}

# Reads KEY=value out of backend/.env (last match wins, quotes/whitespace stripped).
# Shared by cmd_start (API_HOST/API_PORT) and cmd_backup (DATABASE_URL_SYNC).
env_value() {
  grep -E "^$1=" "$BACKEND_DIR/.env" 2>/dev/null | tail -n1 | cut -d= -f2- | tr -d "\"' \r"
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
  # Secrets must never be world/group readable.
  chmod 600 .env

  mkdir -p "$BACKEND_DIR/data"   # every database file lives here
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

  echo "==> Starting research/evolution scheduler (own lease; only acts when its gates pass; logging to $LOG_DIR/research.log)"
  supervise research "$VENV_DIR/bin/python" -m scripts.run_research

  echo "==> Starting API + frontend (restart-on-crash, logging to $LOG_DIR/api.log)"
  # uvicorn's CLI does not read backend/.env, so pick API_HOST / API_PORT up from it here
  # (an already-exported environment variable wins). Default stays loopback.
  API_HOST="${API_HOST:-$(env_value API_HOST)}"; API_HOST="${API_HOST:-127.0.0.1}"
  API_PORT="${API_PORT:-$(env_value API_PORT)}"; API_PORT="${API_PORT:-8000}"
  echo "==> API will listen on ${API_HOST}:${API_PORT}"
  supervise api "$VENV_DIR/bin/uvicorn" app.main:app --host "$API_HOST" --port "$API_PORT"

  echo "==> Starting hourly exit-analytics refresh (trade_analytics/matrix/fitness_forward; runs once immediately, then every hour; logging to $LOG_DIR/analytics.log)"
  supervise analytics bash -c "while true; do '$VENV_DIR/bin/python' -m scripts.refresh_analytics; sleep 3600; done"

  sleep 1
  cmd_status
  echo ""
  echo "Dashboard: http://${API_HOST}:${API_PORT}/"
  echo "Logs:      ./run.sh logs"
  echo "Stop:      ./run.sh stop"
}

cmd_stop() {
  for name in "${SERVICES[@]}"; do
    echo "==> Stopping $name"
    stop_one "$name"
  done
  # The supervisor loop is stopped above, but the python child can survive it (it did on the
  # server, forcing manual pkill). Make sure nothing from THIS project keeps running.
  for pattern in "$VENV_DIR/bin/.*scripts\.run_cycle" "$VENV_DIR/bin/.*scripts\.run_research" "$VENV_DIR/bin/.*uvicorn app\.main" "$VENV_DIR/bin/.*scripts\.refresh_analytics"; do
    pkill -f "$pattern" 2>/dev/null || true
  done
  sleep 1
  for pattern in "$VENV_DIR/bin/.*scripts\.run_cycle" "$VENV_DIR/bin/.*scripts\.run_research" "$VENV_DIR/bin/.*uvicorn app\.main" "$VENV_DIR/bin/.*scripts\.refresh_analytics"; do
    pkill -9 -f "$pattern" 2>/dev/null || true
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

cmd_backup() {
  if ! command -v pg_dump >/dev/null 2>&1; then
    echo "pg_dump not found on PATH - install the postgresql client package for this box's Postgres version." >&2
    exit 1
  fi
  local db_url
  db_url="$(env_value DATABASE_URL_SYNC)"
  if [ -z "$db_url" ]; then
    echo "DATABASE_URL_SYNC not set in $BACKEND_DIR/.env" >&2
    exit 1
  fi
  mkdir -p "$BACKUP_DIR"
  local stamp readable_time backup_path
  stamp="$(date -u +%Y%m%d_%H%M%S)"
  readable_time="$(date -u +"%Y-%m-%d %H:%M:%S UTC")"
  backup_path="$BACKUP_DIR/trading_lab_${stamp}.dump"
  echo "==> Backing up database (started $readable_time) to $backup_path" >&2
  pg_dump "$db_url" -Fc -f "$backup_path"
  echo "==> Done at $(date -u +"%Y-%m-%d %H:%M:%S UTC") ($(du -h "$backup_path" | cut -f1))" >&2
  # Last line, unadorned by the >&2 lines above, so a caller can grab it with
  # `./run.sh backup | tail -1 | cut -d= -f2` (e.g. to feed an scp command).
  echo "BACKUP_PATH=$backup_path"
}

case "${1:-start}" in
  start)   cmd_start ;;
  stop)    cmd_stop ;;
  restart) cmd_stop; sleep 1; cmd_start ;;
  status)  cmd_status ;;
  logs)    cmd_logs ;;
  backup)  cmd_backup ;;
  *)
    echo "Usage: $0 {start|stop|restart|status|logs|backup}" >&2
    exit 1
    ;;
esac
