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

### PostgreSQL sizing and timeouts
Three processes share the server: keep `3 x (DATABASE_POOL_SIZE + DATABASE_MAX_OVERFLOW)` under ~90% of
`max_connections` and set `DATABASE_SERVER_MAX_CONNECTIONS` to match (the app refuses to start otherwise).
`lock_timeout` and `idle_in_transaction_session_timeout` are applied to every pooled connection. Lease expiry is
judged by the **database** clock on PostgreSQL. The `b7d1f3a9c5e2` migration adds CHECK constraints and **pre-flights
existing rows**: if any violate a constraint it aborts, changes nothing and lists the offenders - repair them, re-run.

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
python -m scripts.run_research --new-oos-epoch --reason "monthly refresh"   # OPERATOR ACTION: seal a NEW holdout
```
Every run (including skips and failures) is an `experiments` row; see `/api/evolution/experiments`.
The OOS holdout is **frozen**: it does not move as candles arrive. Renew it deliberately (the reason is recorded
permanently); the old epoch and its evaluations are kept. The log warns when the sealed holdout is older than
`RESEARCH_EPOCH_MAX_AGE_DAYS`. An `epoch_integrity_error` skip means stored candles no longer match what was sealed.

## Ollama credentials (no restart needed)
The worker re-reads `OLLAMA_API_KEY(S)` every `OLLAMA_KEY_REFRESH_SECONDS`; `kill -HUP <worker pid>` forces an
immediate reload that re-tries **every** key. A key that already returned 401/403 stays disabled until its value
changes (so a bad key is never hammered).

## Switching TRADING_MODE
Positions remember the venue that opened them. Switching (e.g. paper -> shadow) with positions still open blocks new
entries (`venue_mismatch` halt reason) until they close; exits keep running. Prefer switching when flat.

## Behaviour change to know about: next-open fills
Paper entries/exits now fill at the **next bar's open** (`PAPER_FILL_TIMING=next_open`). Historical paper statistics
were produced with same-bar-close fills and are **not directly comparable**; trailing stops also count the bar's own
extreme by default. Set `PAPER_FILL_TIMING=signal_close` / `TRAILING_STOP_USES_SAME_BAR_EXTREME=false` only to
reproduce old numbers.

## Secrets hygiene
`python -m scripts.secret_scan` (also run by CI and the pre-commit hook) fails on key-shaped values in any tracked
or untracked-but-not-ignored file. Credentials that were ever committed must be **rotated**; see
[security.md](security.md) and `scripts/purge_secrets_from_history.sh` (dry-run by default; never pushes).

## Tests
```bash
cd backend && .venv/bin/python -m pytest -q                       # SQLite
DATABASE_URL=postgresql+asyncpg://… .venv/bin/python -m pytest -q # the whole suite on PostgreSQL
TEST_POSTGRES_ADMIN_URL=postgresql://postgres@127.0.0.1:55432/postgres .venv/bin/python -m pytest -q tests/test_postgres*.py
```
CI (`.github/workflows/ci.yml`) runs the suite with a real PostgreSQL 16 service so the PG tests never skip.

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
