#!/usr/bin/env bash
# Single entrypoint: sets up (if needed) and runs the whole project —
# DB migrations, the trading worker, and the API + frontend. The database is
# a local SQLite file (backend/trading_lab.db) — no server to install/start.
#
# Usage: ./run.sh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
VENV_DIR="$BACKEND_DIR/.venv"

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

echo "==> Starting trading worker in the background"
python -m scripts.run_cycle &
WORKER_PID=$!
trap 'echo "==> Stopping worker"; kill "$WORKER_PID" 2>/dev/null || true' EXIT

echo "==> Starting API + frontend at http://localhost:8000"
uvicorn app.main:app --host 0.0.0.0 --port 8000
