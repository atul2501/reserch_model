# Experiment Guide

How to run baseline/candidate experiments, compare results, use the research dashboard, and
run/recover the multi-week 500-agent paper/shadow experiment.

All commands assume `cd backend && source .venv/bin/activate` unless noted.

---

## 1. Running a baseline vs. candidate experiment

The experiment runner (`app/research/experiment_runner.py`) always compares two
`StrategyDNA` configs against the **same** active `ResearchEpoch`'s train+validation frame,
and persists both as new, non-overwriting `Experiment` rows.

### Quick start — built-in configs

```bash
python -m scripts.run_experiment --name exit_fixed_pct_stop
python -m scripts.run_experiment --name exit_tighter_atr_stop
```

Prints a baseline/candidate/difference table and prints both new experiment IDs
(`EXP-EVAL-<timestamp>-<hex>`).

### Custom configs

Write a small script (or extend `scripts/run_experiment.py`'s `BUILTIN_CONFIGS` dict):

```python
from app.core.database import AsyncSessionLocal
from app.research.experiment_runner import run_baseline_vs_candidate, render_comparison
from app.schemas.strategy_dna import StrategyDNA

baseline_dna = StrategyDNA(...)
candidate_dna = StrategyDNA(...)

async with AsyncSessionLocal() as db:
    baseline, candidate = await run_baseline_vs_candidate(
        db, baseline_dna=baseline_dna, candidate_dna=candidate_dna, name="my_experiment"
    )
    await db.commit()
    print(render_comparison("my_experiment", baseline, candidate))
```

### What it does NOT do

It never calls `app.research.lockbox.evaluate_oos_once` — the protected final-OOS holdout
is rate-limited (one evaluation per strategy version, one per lineage, per epoch) and
reserved for real promotion-track candidates. Every result from this runner is IN-SAMPLE.
Do not wire arbitrary experimental DNAs into `evaluate_oos_once` — that would burn a real
candidate's one shot at OOS evidence.

### Specifying the dataset / `as_of` / OOS window

The runner always uses `app.research.dataset.get_active_epoch(db, "SOL", "1m")` — whatever
epoch the real research pipeline last sealed. To run against a specific epoch instead of
"whatever is active," pass that `ResearchEpoch` object directly if calling the lower-level
pieces (`ds.load_epoch_candles`, `ds.slice_train_validation`) yourself; there is currently no
CLI flag to select an epoch by ID (only one is ever active at a time by design — see
`MULTI_WEEK_RESEARCH_READINESS_REPORT.md` §1.4).

For `as_of`-bounded analytics (not experiments): `scripts/refresh_analytics.py` now accepts
`as_of` on `refresh_trade_analytics`/`refresh_strategy_regime_matrix` at the Python API level
(not yet a CLI flag — pass it directly if scripting a bounded replay).

---

## 2. Comparing experiments

### From the CLI

`render_comparison()`'s output (shown automatically by `scripts/run_experiment.py`) gives the
Baseline / Candidate / Difference table directly.

### Programmatically

```python
from app.research.experiment_runner import list_experiments, diff_experiments

experiments = await list_experiments(db, kind="evaluation", limit=50)   # newest first
diff = diff_experiments(experiments[0], experiments[1])                  # {field: (a, b, delta)}
```

### From the dashboard

Open `/experiments` (see §4). Click any two rows to see their diff rendered as a table.
Filter by `kind` (`evaluation` = baseline/candidate runs, `evolution` = real research
cycles, `oos` = protected final-OOS evaluations) using the dropdown.

### Reading the sample label

Every result carries `sample_label`: `IN-SAMPLE` at ≥30 trades
(`app.research.lockbox.FULL_CONFIDENCE_TRADES`), else `PROMISING — REQUIRES UNSEEN DATA`.
Never treat the second label as a positive result — it means exactly what it says: not
enough evidence yet, not "looks good."

---

## 3. Verifying `as_of` boundaries yourself

```bash
pytest tests/test_as_of_boundaries.py -v
```

Each test name states the boundary it proves (exactly-at, immediately-before,
immediately-after, empty-future, UTC-midnight). To check a NEW function you're about to add
an `as_of` parameter to, follow the same pattern: seed rows straddling the boundary, assert
the boundary row's inclusion/exclusion explicitly, don't just check "the function runs."

---

## 4. Starting the dashboard

```bash
./run.sh start          # starts worker + research scheduler + API/dashboard together
```

or, API only (e.g. to inspect a snapshot copy without running the trading loop):

```bash
DATABASE_URL="sqlite+aiosqlite:///path/to/snapshot.db" \
DATABASE_URL_SYNC="sqlite:///path/to/snapshot.db" \
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Pages:
- `/` — system health, population, evolution, trading, risk, agent detail (click any
  leaderboard row, or paste an agent ID into the Agent Detail box).
- `/exits` — exit research: MFE/MAE/left-on-table distributions, reversal rate, exit-reason
  and trade-quality-class breakdowns. Filter by family/generation/side/regime/agent/date.
- `/experiments` — experiment log + baseline-vs-candidate diff (see §2).

If `API_AUTH_REQUIRED=true` in `.env`, the dashboard will prompt for an API key on first
load (stored in `sessionStorage`, cleared when the tab closes).

**If you ever see a red "LIVE TRADING MODE IS ENABLED" banner during this research phase**,
that is unexpected — check `TRADING_MODE` in `.env` immediately.

---

## 5. Starting the 500-agent paper/shadow experiment

```bash
# Confirm settings first
grep -E "^(AGENT_COUNT|TRADING_MODE|DATABASE_URL)=" backend/.env
# Expect AGENT_COUNT=500, TRADING_MODE=paper (or shadow)

# Back up the current database first (never skip this before a fresh-start reset)
mkdir -p backend/data/backups
cp backend/data/trading_lab.db* backend/data/backups/ 2>/dev/null
mv backend/data/backups/trading_lab.db backend/data/backups/trading_lab_$(date +%Y%m%d_%H%M).db

./run.sh start
./run.sh status
./run.sh logs          # Ctrl+C to leave the log view
```

This is the same procedure documented in the repo's own `model.txt` runbook — nothing new
was introduced for the 500-agent case specifically; the data model already supports it
(`MULTI_WEEK_RESEARCH_READINESS_REPORT.md` §8).

**Do not switch `TRADING_MODE` to `live` as part of this experiment.**

### Monitoring during the run

- Dashboard (§4) for live status.
- `./run.sh logs` for raw worker/research/API logs.
- Periodically: `python -m scripts.refresh_analytics` to keep `/exits` current, then
  `python -m scripts.report_trade_quality` or the dashboard for a snapshot.
- Watch for the dashboard's alert banner (worker down, market data stale, database
  unreachable, kill switch active, live mode).

---

## 6. Stopping safely

```bash
./run.sh stop
```

Stops worker, research scheduler, and API cleanly (each process handles SIGTERM and logs a
`worker.stopped`-style event before exiting — confirmed by this phase's recovery test, see
`MULTI_WEEK_RESEARCH_READINESS_REPORT.md` §9). No data is deleted. The SQLite WAL is
checkpointed normally on clean shutdown.

To stop only the worker (leaving research/API running) for a targeted restart:

```bash
cd backend
WORKER_PID=$(cat .run/worker.pid)
pkill -P "$WORKER_PID"; kill "$WORKER_PID"; rm -f .run/worker.pid
```

---

## 7. Recovering after a restart

```bash
./run.sh start
```

The worker detects any gap since its last completed cycle and runs its existing catch-up
replay path automatically (`cycle.catchup_truncated_bars_not_replayed` in the logs is
expected and not an error — it means the worker is skipping bars it can't meaningfully
replay rather than silently pretending they didn't happen). `worker_cycles.cycle_id` is
unique per cycle — the pipeline will never reprocess or duplicate a cycle it already
completed, verified directly by this phase's recovery test (zero duplicate `cycle_id`,
`trade.id`, `order.client_order_id`, or `decision.id` across a real stop/restart).

If you suspect something went wrong after a restart, check in this order:
1. `./run.sh status` — are all three processes actually running?
2. `./run.sh logs` — any `ERROR`-level events since startup?
3. `sqlite3 backend/data/trading_lab.db "select count(*) - count(distinct cycle_id) from worker_cycles;"`
   — should be `0`. Same pattern works for `trades.id`, `orders.client_order_id`,
   `decisions.id`.
4. The dashboard's alert banner (§4) — it will surface a stopped worker or stale data
   automatically.

---

## Verifying the guide itself

Every command in §1, §2, §6, and §7 was actually run against real data during this phase
(see `MULTI_WEEK_RESEARCH_READINESS_REPORT.md` §2, §3, §9) — this is not a theoretical guide.
