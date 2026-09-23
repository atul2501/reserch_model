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

## Database size / `decisions` growth
Before this fix every agent wrote a `decisions` row on every candle (500 x 1/min = ~720k rows/day), 99% of them
"no signal / holding", each with a ~1.4 KB copy of the market snapshot (already stored once per candle in
`market_features`). Now only **actionable** agent-candles (entries, exits, vetoes, risk rejections, cooldown /
daily-limit skips) write a row, and `market_context` is no longer copied. Expected growth: a few MB/day.

Diagnose (PostgreSQL):
```sql
SELECT relname, pg_size_pretty(pg_total_relation_size(oid)) total FROM pg_class
WHERE relkind='r' AND relnamespace='public'::regnamespace ORDER BY pg_total_relation_size(oid) DESC LIMIT 8;
```
Diagnose (SQLite): `sqlite3 backend/data/trading_lab.db "select name, sum(pgsize)/1048576 MB from dbstat group by name order by 2 desc limit 8;"`

One-time cleanup of an existing database (take a backup / `pg_dump` first; **stop the worker**):
```bash
./run.sh stop
cd backend
python -m scripts.prune_decisions --dry-run --older-than-days 0     # shows what would go
python -m scripts.prune_decisions --older-than-days 0 --strip-context --vacuum
alembic upgrade head        # SQLite: do this AFTER pruning (batch ALTER rebuilds the table)
./run.sh start
```
Rows linked to an order or trade are never deleted. `--vacuum` returns disk to the OS (`VACUUM` on SQLite,
`VACUUM (FULL, ANALYZE) decisions` on PostgreSQL, which takes an exclusive lock; use `pg_repack` if you cannot stop
the worker). On a 496 MB production backup this produced 8.4 MB with all 1,033 orders / 930 trades intact.
Routine housekeeping: `python -m scripts.prune_decisions` (deletes legacy no-op rows older than `DECISION_RETENTION_DAYS`).

## Where the database files live
Everything SQLite-related is in **one folder: `backend/data/`** (`trading_lab.db`, `backups/`, and the test database).
Relative paths in `DATABASE_URL` are resolved from `backend/`, not from the directory you launch from, so the app,
alembic, the scripts and the tests always use the same file. The folder is git-ignored and created automatically.

Moving an existing install (stop everything first so no `-wal/-shm` file is in flight):
```bash
cd ~/reserch_model && ./run.sh stop
mkdir -p backend/data
mv backend/trading_lab.db* backend/data/ 2>/dev/null
mv backend/backups backend/data/ 2>/dev/null
sed -i 's#^DATABASE_URL=.*#DATABASE_URL=sqlite+aiosqlite:///./data/trading_lab.db#; s#^DATABASE_URL_SYNC=.*#DATABASE_URL_SYNC=sqlite:///./data/trading_lab.db#' backend/.env
./run.sh start
```
