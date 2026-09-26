# PostgreSQL Migration Guide

How to run the SQLite → PostgreSQL migration — locally (already done, this session) and,
separately, in production (not done, not started — this section documents the same
procedure using production-specific configuration).

---

## Local Migration

### Prerequisites

- PostgreSQL running locally (this session used Postgres 16 via Homebrew, already
  installed — `brew services list | grep postgres`).
- A database and role for the app. This session used database `trading_lab`, role
  `trading_lab`:
  ```sql
  DROP DATABASE IF EXISTS trading_lab;   -- only if recreating; see note below
  CREATE DATABASE trading_lab OWNER trading_lab;
  ALTER ROLE trading_lab WITH PASSWORD '<a real local password>' LOGIN;
  ```
  **Note**: local Homebrew Postgres uses trust auth for loopback connections by default
  (the password is accepted but not actually checked) — this is fine for local dev but
  means the password in `backend/.env` is decorative locally, not a real access control.
  It's still set to a real value so the connection-string *format* matches what production
  will actually need to enforce.

### Step 1 — Point the app at Postgres

Set `backend/.env` (real credentials — never `.env.example`, which stays placeholder-only):
```env
DATABASE_URL=postgresql+asyncpg://trading_lab:<password>@127.0.0.1:5432/trading_lab
DATABASE_URL_SYNC=postgresql://trading_lab:<password>@127.0.0.1:5432/trading_lab
```
Every real runtime process (API, worker, research scheduler, Alembic) now requires this —
`app/core/config.py`'s `_require_postgres_outside_tests` validator raises a clear
`ValueError` at startup if `DATABASE_URL` is still a `sqlite://` URL and `TESTING` isn't
set. There is no silent SQLite fallback.

### Step 2 — Apply the schema

```bash
cd backend && source .venv/bin/activate
alembic upgrade head
```
Idempotent — safe to re-run.

### Step 3 — Migrate the data

**Back up first, always:**
```bash
mkdir -p backend/data/backups
cp backend/data/trading_lab.db backend/data/backups/trading_lab_pre_postgres_migration_$(date -u +%Y%m%d_%H%M%S).db
```

Then:
```bash
python -m scripts.migrate_sqlite_to_postgres \
    --sqlite-path backend/data/trading_lab.db \
    --pg-url postgresql+asyncpg://trading_lab:<password>@127.0.0.1:5432/trading_lab \
    --skip-schema-upgrade   # already done in Step 2
```

Never touches the source SQLite file (read-only access only). Copies every table in
FK-safe order, preserving every ID. Prints:
- a row count for every table, source → destination, flagged `OK`/`MISMATCH`;
- an **aggregate verification summary** (total/active/dead agents, total trades, sum
  net_pnl, sum fees, total decisions, total experiments, generation/strategy counts,
  earliest/latest trade timestamp) comparing SQLite vs. Postgres — this is what actually
  proves the *values*, not just the row counts, came across intact (a swapped column or a
  mis-cast enum would still pass a row-count-only check).

Exits non-zero if any row count or aggregate doesn't match — treat that as "do not use this
migration," not a warning to note and move past.

### Step 4 — Verify

- The script's own output (above) is the primary verification.
- Spot-check foreign-key integrity directly:
  ```sql
  SELECT count(*) FROM trades t LEFT JOIN agents a ON a.id = t.agent_id WHERE a.id IS NULL;
  -- expect 0, repeat for positions/decisions -> agents, agents -> strategy_versions, etc.
  ```
- Re-run the schema-drift check: `pytest backend/tests/test_postgres.py -q` (needs a
  reachable Postgres at `TEST_POSTGRES_ADMIN_URL`, default `127.0.0.1:55432` — a
  **different, throwaway** instance from your real migration target; don't point it at the
  database you just migrated into).

### Step 5 — Run the app on Postgres

```bash
./run.sh start
curl -s http://127.0.0.1:8000/api/system/health   # or /api/system/status for the dialect field
```
Confirm `database.dialect == "postgresql"` and grep the logs for any `sqlite` mention
(there should be none from this point forward).

### Step 6 — Recovery test

Before trusting this for real use, prove the worker can be stopped and restarted without
data loss or duplication:
```bash
cd backend
WORKER_PID=$(cat .run/worker.pid)
pkill -P "$WORKER_PID"; kill "$WORKER_PID"; rm -f .run/worker.pid
# restart:
"$PWD/.venv/bin/python" -m scripts.run_cycle >> logs/worker.log 2>&1 &
disown; echo $! > .run/worker.pid
```
Then verify no duplicates:
```sql
SELECT count(*) - count(DISTINCT id) FROM trades;               -- expect 0
SELECT count(*) - count(DISTINCT client_order_id) FROM orders;  -- expect 0
SELECT count(*) - count(DISTINCT id) FROM decisions;             -- expect 0
SELECT count(*) - count(DISTINCT cycle_id) FROM worker_cycles;   -- expect 0
```

### Step 7 — Retire SQLite (only after every above step passes)

```bash
./run.sh stop
cp backend/data/trading_lab.db backend/data/backups/trading_lab_FINAL_ARCHIVE_before_deletion_$(date -u +%Y%m%d_%H%M%S).db
md5 backend/data/backups/trading_lab_pre_postgres_migration_*.db backend/data/backups/trading_lab_FINAL_ARCHIVE_*.db
# if checksums match (proves zero SQLite writes since the migration), it's safe to delete:
rm -f backend/data/trading_lab.db backend/data/trading_lab.db-wal backend/data/trading_lab.db-shm
./run.sh start
ls backend/data/trading_lab.db   # should report "No such file" - confirms nothing recreated it
```
**Get explicit human sign-off before this step, every time.** It is the one irreversible
action in this whole procedure (a backup makes it *recoverable*, not *not worth pausing
for*).

---

## Future Production Migration

**The production migration must be performed with production-specific environment
variables/secrets and must not use local credentials.** This repository has not connected
to, queried, or modified any production system as part of preparing this guide — the
procedure below is written from the local migration's real, executed experience, but every
value production actually uses (host, database name, role, password, `TEST_POSTGRES_ADMIN_URL`
equivalents) must come from production's own configuration/secret management, never copied
from this repo's local `.env`.

The steps are **identical in shape** to Local Migration above — that's the point of this
architecture: the same code, the same script, the same Alembic chain, driven entirely by
environment configuration:

```text
LOCAL:                              PRODUCTION:
  Existing local SQLite               Existing production SQLite
    ↓                                   ↓
  Local PostgreSQL                    Production PostgreSQL
```

Differences for production, all configuration-only (no source-code change):

- `DATABASE_URL`/`DATABASE_URL_SYNC` point at the production Postgres host, using
  production secret management (never a value pasted into any file in this repo).
- `DATABASE_SERVER_MAX_CONNECTIONS` must be set to production's actual
  `SHOW max_connections`, not the local default — `app/core/config.py`'s
  `_check_pool_budget` validator refuses to start if `3 × (pool_size + max_overflow)`
  would exceed 90% of whatever this is set to.
- The pre-migration backup, and the final archive before any SQLite retirement decision,
  must follow production's own backup/retention policy, not this repo's `backend/data/backups/`
  convention (that convention is a local-dev, single-machine convenience).
- Production's recovery test (Step 6) should be run against a maintenance window or a
  staging replica first, not the live production worker, given this session's own finding
  (§ Known limitations below) that a long-running analytics refresh against Postgres can
  overlap with live writes in ways it never did against SQLite's faster local I/O.
- **A human must explicitly approve the SQLite retirement step (Step 7) for production,
  separately from local approval.** Local approval does not transfer.

### Known limitations found during the local migration (apply to production too)

- **`refresh_strategy_regime_matrix` (part of `scripts/refresh_analytics.py`) takes
  noticeably longer against Postgres than SQLite** (network round-trips vs. local file
  I/O) — long enough, against a live, actively-trading system, that its own built-in
  "raw tables must not mutate during a read-only refresh" safety check can correctly detect
  legitimate concurrent writes from the live worker and refuse to complete. This is the
  check working as designed (failing loud on an assumption it can no longer guarantee), not
  a bug — but production should either run this specific refresh during a low-activity
  window, or budget for optimizing its DB access pattern (fewer round trips) before relying
  on it against a live, continuously-writing production database. `refresh_trade_analytics`
  itself (the more heavily-used phase) completed successfully in the same environment.
- The default `DATABASE_IDLE_IN_TRANSACTION_TIMEOUT_MS=120000` (2 minutes) can be too tight
  for the same long-running, Python-computation-heavy analytics refresh — this session
  raised it via a one-off environment override to complete the matrix refresh. Consider a
  dedicated, longer timeout profile for scheduled analytics jobs vs. the interactive/
  trading-loop connections that should stay tightly bounded.
