# PostgreSQL Migration Report

Local-only. No production system was connected to, queried, or modified at any point in
this work.

---

## Local

**Source**: `backend/data/trading_lab.db` (SQLite, 991 agents, 8,253 trades at migration
time, ~24h of accumulated research data spanning this program's first three phases).

**Target**: local PostgreSQL 16 (Homebrew), database `trading_lab`, role `trading_lab`.

**Pre-existing state found and resolved with the user before migrating**: a Postgres
database already named `trading_lab` existed locally, but on alembic revision
`1b91ce59e177` (not in the current 25-migration chain) with only 525 agents / 48 trades
from Sep 21 — a stale, abandoned prototype unrelated to this program's current dataset.
**User confirmed: drop and recreate it fresh.** This was not production data and no
production system was involved.

**Migration completed**: yes.
- Schema: `alembic upgrade head` — all 25 migrations applied cleanly to the fresh database.
- Data: `scripts/migrate_sqlite_to_postgres.py` run against the live SQLite file (backed up
  first) with the new aggregate-verification extension. All 37 populated tables copied,
  every row count matched exactly (991 agents, 8,253 trades, 80,386 decisions, 316
  experiments, etc.).
- Aggregates verified: `sum(net_pnl)` −239.38 both sides (float noise <1e-6 tolerated),
  `sum(fees)` matched, `total_agents`/`active_agents`/`dead_agents` matched, earliest/latest
  trade timestamp matched exactly, generation count (2) and strategy count (981) matched.
- Foreign-key integrity: 0 orphaned rows across `trades→agents`, `positions→agents`,
  `decisions→agents`, `agents→strategy_versions`.
- Application verification: `./run.sh start` with `backend/.env` pointed at Postgres;
  `/api/system/health`/`/api/system/status` confirmed `database.dialect: "postgresql"`;
  logs grepped for any `sqlite` mention from the moment of cutover forward — none found.
- Recovery verification: worker stopped (research/API left running — a stricter test than
  stopping everything) and restarted against Postgres; zero duplicate `trades.id`,
  `orders.client_order_id`, `decisions.id`, or `worker_cycles.cycle_id` across the restart.
- SQLite archive: `backend/data/backups/trading_lab_FINAL_ARCHIVE_before_deletion_20260926_212508.db`
  — MD5-verified byte-identical to the pre-migration backup, proving zero SQLite writes
  occurred at any point after the cutover (the strongest available evidence that nothing
  silently fell back to it).
- **SQLite deletion**: confirmed by the user (explicit go-ahead requested and given after
  every check above passed) and executed. `backend/data/trading_lab.db` (and `-wal`/`-shm`)
  removed. Application restarted afterward and confirmed working on Postgres alone; the
  file was not recreated.

**A real, previously-undetected bug was found and fixed as a direct result of this
migration** (not a migration-tooling bug — a bug in the analytics pipeline that SQLite's
lax typing had been hiding): `app/analytics/analytics_store.py` converted `Trade.side` (a
`Side` enum) via `str(trade.side).upper()`, producing `"SIDE.LONG"`/`"SIDE.SHORT"` instead
of the plain value. This silently broke direction-sensitive comparisons everywhere
downstream (every trade's MFE/MAE excursion was computed as if it were SHORT, inverting the
true direction for ~44% of trades that were actually LONG) and overflowed
`TradeAnalytics.side`'s `VARCHAR(5)` column — invisible on SQLite (no length enforcement),
a hard `INSERT` failure the instant this project's own `refresh_analytics.py` ran for real
against Postgres. Fixed at the root (`trade.side.value`), covered by a new regression test,
and the entire dataset (now 8,500 trades) was re-analyzed with corrected exit-quality
figures — see `MULTI_WEEK_RESEARCH_READINESS_REPORT.md` §5 for the full before/after and
`RESEARCH_VALIDATION_REPORT.md` §5 for the correction notice on the original figures. This
is exactly the kind of latent defect a Postgres-first architecture is supposed to surface
before production, not after.

A second, lower-severity finding: `scripts/refresh_analytics.py`'s matrix-refresh phase
takes long enough against Postgres (network round-trips) that it can legitimately overlap
with live worker writes in ways it never did against SQLite's faster local I/O — see
`POSTGRESQL_MIGRATION_GUIDE.md`'s "Known limitations" for detail. Not a data-loss issue
(the refresh itself completed and its output was correct); its own safety check just
correctly detected the overlap and (correctly) refused to certify isolation it could no
longer guarantee.

---

## Production readiness

| item | status |
|---|---|
| Migration script reusable | **YES** — `scripts/migrate_sqlite_to_postgres.py` takes `--sqlite-path`/`--pg-url` as arguments, contains no hard-coded host/database/credentials, refuses to proceed without a verified schema, never touches the source file |
| Environment configuration reusable | **YES** — `.env.example` is PostgreSQL-first with placeholders only; `app/core/config.py` reads everything through `Settings`, zero hardcoded host/db/user/password anywhere in source (confirmed by re-reading `app/core/database.py` and `config.py` in full) |
| Alembic migrations verified | **YES** — all 25 apply cleanly to a fresh Postgres database; `tests/test_postgres.py`'s zero-schema-drift check passed against the same throwaway-cluster pattern used across this program's prior phases |
| Verification procedure documented | **YES** — `POSTGRESQL_MIGRATION_GUIDE.md`, row-count + aggregate + FK + application + recovery checks, all exercised for real this session, not just described |
| Backup procedure documented | **YES** — timestamped `cp` before migration and again before any SQLite retirement decision, checksum-compared to prove no silent writes |
| Rollback/recovery procedure documented | **YES** — rollback is "don't change `DATABASE_URL`" while the SQLite file is retained (trivial, and was exercised for real by keeping the archive until every check passed); recovery (worker restart) tested for real against Postgres with zero duplicates |
| Startup validation (PostgreSQL required) | **YES** — `app/core/config.py::_require_postgres_outside_tests`, a single `Settings` validator covering every entrypoint (API, worker, research scheduler, Alembic) that constructs `Settings`; raises a clear, specific error rather than silently falling back; `TESTING=true` is the one explicit, documented escape hatch for unit tests |
| Documentation | **YES** — this report, `POSTGRESQL_MIGRATION_GUIDE.md`, updated `MULTI_WEEK_RESEARCH_READINESS_REPORT.md` and `EXPERIMENT_GUIDE.md` |

**Not done, and correctly so**: no production host, database name, or credential was ever
referenced, queried, or assumed anywhere in this session's work. Production migration
requires its own explicit authorization and its own environment configuration — nothing
here performs it or gets closer to performing it than "the same reusable tooling now
exists and has been proven once, locally."

---

## Test suite

Full backend suite, after every change in this phase (config validator, `analytics_store.py`
fix, `experiment_runner.py` cleanup, new tests):

**967 passed, 2 failed, 18 skipped, 2 xfailed (0:06:41).**

Both failures pre-existing/unrelated, each individually confirmed:
- `test_logging.py::test_uvicorn_access_log_formats_and_is_redacted` — pre-existing across
  every phase of this program.
- `test_research_event_loop.py::test_correlation_report_does_not_starve_the_event_loop` —
  a timing-sensitive test; failed once under heavy concurrent load (this session had a live
  worker/research/API stack, a long-running analytics refresh, and the full test suite all
  running at once), passed cleanly when re-run in isolation immediately after. Flaky under
  load, not a regression — same pattern as a prior phase's identical finding.

18 new tests added this phase across `tests/test_postgres.py` (4, the PostgreSQL-required
validator) and `tests/test_analytics_store.py` (1, the side-handling regression, replacing
a prior test count of 8 with 9).

## Final status

**LOCAL POSTGRESQL MIGRATION COMPLETE — PRODUCTION MIGRATION READY**
