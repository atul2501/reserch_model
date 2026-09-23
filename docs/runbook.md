# Runbook

## Start / stop
```bash
./run.sh start     # migrations, bootstrap (if empty), then worker + research + API (each restart-on-crash)
./run.sh status | logs | stop
```
Production: systemd units in `docs/systemd/` (`trading-worker`, `trading-research`, `trading-api`), secrets in
`/etc/trading-lab/env`, PostgreSQL via `DATABASE_URL=postgresql+asyncpg://…`, `alembic upgrade head` first.

## PostgreSQL
```bash
export DATABASE_URL=postgresql+asyncpg://trading:***@127.0.0.1:5432/trading_lab
cd backend && alembic upgrade head            # all revisions are additive & preserve history
python -m scripts.bootstrap_population        # only if the database has no generation yet
```
SQLite (dev/tests) runs in WAL mode; production must use PostgreSQL (pool, `statement_timeout`, partial
unique indexes, immutability triggers).

## Health
| Symptom | Where to look |
|---|---|
| Red banner "TRADING WORKER IS NOT RUNNING" | `/api/system/status` -> `worker.heartbeat_age_seconds`; `./run.sh logs`; a second worker holding the lease logs `worker.already_active_refusing_to_trade` |
| "MARKET DATA STALE / GAP" | `market_data_gap_unrecovered` in worker logs; entries are halted automatically and resume when the gap heals |
| Council always INCOMPLETE | `/api/system/ollama` (operator): unhealthy keys by index; rotate credentials then restart the worker (or call `refresh_keys()`) |
| Cycle latency high | `/metrics` `cycle_latency_seconds`, council `latency_seconds` |

## Emergency stop
```bash
curl -X POST -H "X-API-Key: $OPERATOR_KEY" -H 'content-type: application/json' \
     -d '{"active": true, "reason": "manual stop"}' http://127.0.0.1:8000/api/system/kill-switch
```
Set `active: false` to resume. Exits and stops always keep running.

## Research
```bash
python -m scripts.run_research --force        # one cycle now (ignores interval/age/history gates)
python -m scripts.run_research --once         # run only if due
```
Every run (including skips and failures) is an `experiments` row; see `/api/evolution/experiments`.
A previously consumed OOS slice cannot be reused: a *new* epoch (new data) is required.

## Tests
```bash
cd backend && .venv/bin/python -m pytest -q                       # SQLite
DATABASE_URL=postgresql+asyncpg://… .venv/bin/python -m pytest -q # PostgreSQL (also runs tests/test_postgres.py)
```
