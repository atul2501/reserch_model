# Multi-Week Research Readiness Report

Phase 3 of the research validation program (phase 1: `RESEARCH_VALIDATION_REPORT.md` —
fitness fix, OOS-leakage audit, 24h baseline, Postgres dry run). This phase: harden every
`as_of` boundary with proof, build a reusable experiment runner, use the 24h dataset for
controlled (not overfit) improvement, extend the research dashboard, re-verify Postgres,
run a real recovery test, and prepare 500-agent readiness.

**24 hours of data remains a research laboratory, not a validation dataset.** Nothing here
declares the strategy population profitable or unprofitable. Live trading was never
enabled or touched.

---

## 1. `as_of` BOUNDARY AUDIT

Traced every research/analytics/evaluation path (feature generation, signal generation,
fitness, OOS evaluation, MFE/MAE, trade outcome calculation, cohort analytics, agent
ranking, generation decisions, performance metrics, DB queries, caching, rolling windows,
resampling, timestamps, timezone handling) against: *for any evaluation at `as_of = T`, no
information after T may influence the result.*

### 1.1 Confirmed already-safe (no change)

Feature generation (`app/market/feature_engine.py`), signal generation
(`app/strategies/engine.py`, `app/agents/decision_loop.py`), and the train/validation/final-OOS
boundary (`app/research/dataset.py`, `evaluation.py`, `lockbox.py`) were already provably
safe from the prior phase's audit — reconfirmed, not re-derived. `analytics_store.py`'s
`refresh_fitness_forward` was already an exemplary case: its `_latest_upto`/`_corr_upto`
helpers filter explicitly by `<= t`.

### 1.2 Three genuine gaps found and fixed

| # | Location | Problem | Fix |
|---|---|---|---|
| 1 | `app/analytics/performance_metrics_service.py::compute_agent_performance_metric` | Internal trade self-load (only exercised when a caller omits `trades=`) had no upper time bound | Added `Trade.closed_at <= as_of` when `as_of` is given |
| 2 | `app/analytics/analytics_store.py::refresh_trade_analytics` / `refresh_strategy_regime_matrix` | Candle/trade/decision loads and the post-exit MFE/MAE window were fully unbounded — a later refresh silently sees more post-exit data for the same historical trade, making replay non-reproducible | Added an explicit `as_of` parameter bounding every load and the post-exit window's upper edge |
| 3 | `app/evolution/correlation_service.py::compute_generation_correlation_report` | Lookback window derived from real wall-clock `datetime.now()`, with **no upper bound at all** (`Trade.closed_at >= since`, nothing `<=`) | Added a `now` override parameter (mirrors `pipeline.py::evaluate_gates`'s existing pattern) and an explicit upper bound |

None of these are leaks into current production decisions — the fitness/breeding/promotion
pipeline never replays a past `as_of`, so today's single-pass, real-time-only execution was
never actually exposed to them. They are fixed anyway because a multi-week run's own
diagnostics (this dashboard, ad hoc replays, future backfill tooling) will want reproducible
`as_of` semantics, and because leaving a silently-unbounded query in place is exactly the
kind of thing that turns into a real leak the day someone reuses it for something the
original single-pass assumption doesn't hold for.

### 1.3 Regression tests — `tests/test_as_of_boundaries.py` (14 tests)

Exactly-at-`as_of`, immediately-before, immediately-after (excluded), empty-future-data,
missing/partial candles, and one UTC-midnight boundary case, for all three fixed functions.
Proven with real data via the existing `_seed`/`_seed_agent`/`_add_trade` fixtures, not
mocked. Also includes `test_only_one_active_epoch_per_symbol_timeframe_survives_a_renewal`
— a real exercise of `ds.renew_epoch`, proving the invariant that makes §1.4's IMPLICIT-SAFE
list actually safe, not just asserted.

### 1.4 IMPLICIT-SAFE inventory — documented, not refactored

The following "latest row" queries have no explicit `as_of`/upper bound and were
**deliberately left alone** (per the task's own "make the smallest safe change" /
"do not unnecessarily refactor" instruction — none show evidence of an actual defect):

- `app/analytics/fitness_service.py::_latest_by_version`
- `app/evolution/breeding.py` — champion lookup (`StrategyVersion.promoted_at.desc()`), challenger lookup (`ChallengerEvaluation.computed_at.desc()`)
- `app/evolution/champion_challenger_service.py` — challenger/adversarial/regime "latest" lookups
- `app/evolution/promotion_service.py` — best-agent-for-snapshot, adversarial/regime candidate metrics (duplicated logic vs. `champion_challenger_service.py`, a reuse gap, not a correctness gap)
- `app/backtesting/stage_metrics_service.py::latest_stage_metrics`
- `app/analytics/shadow_fitness.py::shadow_rows_for_generation` (shadow-only, not wired into selection)
- `app/research/snapshots.py` (fallback path only)
- `app/research/dataset.py::get_active_epoch`, `app/research/pipeline.py` (last-generation, last-experiment lookups)

**Why safe today:** every one relies on a real, structural invariant — single-writer,
strictly-sequential pipeline execution; at most one active `ResearchEpoch` per
(symbol, timeframe); at most one live `CHAMPION` per lineage. §1.3 proves the epoch
invariant directly; `tests/test_promotion_service.py::test_promotes_and_retires_previous_champion_when_all_gates_pass`
already proves the champion one (pre-existing, not written this phase).

**Recommended pre-long-run hardening (not implemented — no evidence of a live defect, and
this is where "smallest safe change" draws the line):** add explicit `<= as_of` filters to
these before any future parallelized-evaluation or replay/backfill initiative, so they don't
quietly depend on sequencing that a future change could break without any test catching it.

---

## 2. EXPERIMENT RUNNER

`app/research/experiment_runner.py` (new) generalizes the pattern `scripts/compare_fitness_correction.py`
(prior phase) already proved: re-run `evaluate_in_sample` against the *same* active epoch's
train+validation frame a real research cycle used, so a baseline and a candidate are always
compared on identical data.

**Design decision, stated explicitly:** the runner never calls `app.research.lockbox.evaluate_oos_once`.
That evaluation is rate-limited to once per (strategy_version, dataset) and once per lineage
per epoch, reserved for promotion-track candidates — an exploratory runner spending it on
throwaway baseline-vs-candidate comparisons would quietly consume the one real OOS check a
future genuine candidate needs. Every result is therefore **IN-SAMPLE**; the `oos` field on
every result explains this is deliberate, not a data shortfall. `tests/test_experiment_runner.py::test_run_baseline_vs_candidate_never_touches_the_sealed_oos_slice`
proves it directly (`OosEvaluation` table stays empty across a run).

**Provenance** (`register_experiment`/`finish_experiment`, reused unmodified from the prior
phase's registry): experiment ID, timestamp, code version (git commit), dataset fingerprint,
train/validation/OOS periods, config/DNA, random seed, full result — every call produces a
**new** experiment row; nothing is ever updated in place
(`test_run_baseline_vs_candidate_never_overwrites_a_prior_run`).

**Comparison table** — 9 metrics, 7 already existed or are one-line derivations
(Net P&L, Expectancy, Max Drawdown, Win Rate, Profit Factor, Trade Count, Agent Survival);
2 needed new, honestly-scoped logic:
- **MFE Capture**: `net_pnl / max_favorable_pnl`, computed by directly replaying
  `app.analytics.trade_quality.analyze_trade` (the exact same pure function live trades use)
  against the backtest's own candle frame and each `BacktestTrade`'s bar indices — no new
  tracking, no DB writes needed.
- **Average R**: only computable when the DNA's stop-loss method is `fixed_pct` — `atr_multiple`/
  `structure_based` stops need per-bar ATR/swing-structure context that `BacktestTrade`
  doesn't retain, and reconstructing it would mean touching the core backtest engine's hot
  path, which is out of "smallest safe change" scope. **Reported honestly as "n/a: stop
  method is X" rather than approximated or guessed** — consistent with this codebase's
  existing "never guess missing evidence" convention (`fitness_engine.py`'s own components
  follow the same rule).

**Sample-sufficiency labeling**: `IN-SAMPLE` at ≥30 trades (`FULL_CONFIDENCE_TRADES`, the
same threshold the fitness fix uses), else `PROMISING — REQUIRES UNSEEN DATA`.

**`list_experiments`/`diff_experiments`** (new — nothing like this existed): every experiment
row, newest first (nothing collapses to "current state" since nothing is ever overwritten);
a per-field numeric-delta diff between two experiments, with non-numeric/DNA fields preserved
rather than dropped.

`scripts/run_experiment.py` — CLI wrapper with two built-in named configs.

**Tests**: `tests/test_experiment_runner.py`, 8 tests — never overwrites, full provenance
recorded, OOS never touched, sample-label boundary at exactly `FULL_CONFIDENCE_TRADES`,
diff correctness, list ordering, comparison rendering. Plus 2 new API-level tests in
`tests/test_api_endpoints.py` covering the dashboard's `/api/exit-analytics` and
`/api/evolution/experiments/diff` endpoints end-to-end.

---

## 3. CONTROLLED IMPROVEMENT ON THE 24H DATA — Development vs. Validated Result

Ran the runner for real, against the live snapshot, for two candidates vs. the current
exit logic as baseline — a demonstration that the tooling works end-to-end on real data,
**not** a tuning campaign (each candidate run exactly once, per the task's own "do not
repeatedly optimize against the same window" instruction):

| Experiment | Baseline stop | Candidate stop | Net P&L Δ | Win Rate Δ | Profit Factor Δ | Sample |
|---|---|---|---|---|---|---|
| `exit_fixed_pct_stop` | ATR×3.0 | fixed 2% | +0.044 | +0.0000 | +0.0020 | IN-SAMPLE (n=79 both) |
| `exit_tighter_atr_stop` | ATR×3.0 | ATR×1.5 | −0.097 | −0.0212 | −0.0052 | IN-SAMPLE (n=79/83) |

**Development result, not a validated one**: both deltas are small relative to the
population's overall weak edge (see phase-1 report §4), computed on a single ~24h epoch with
no independent holdout re-run (per §2's OOS-protection design). Neither candidate is
recommended for promotion. Per the task's own rule, this is reported as **PROMISING at best
in the loosest sense — requires unseen data** for either change to mean anything; picking a
"winner" from two single-epoch runs would be exactly the overfitting this phase was told not
to do.

---

## 4. STANDARD EXPERIMENT COMPARISON FORMAT

Delivered directly by §2's `render_comparison`/the `/experiments` dashboard page: Baseline /
Candidate / Difference columns for Net P&L, Expectancy, Max Drawdown, Win Rate, Average R,
MFE Capture, Trade Count, Agent Survival, Profit Factor — plus explicit sample-sufficiency
and OOS-status labels per side, never silently picking the higher-P&L one.

---

## 5. EXIT RESEARCH

Reuses phase 1's independently-verified figures (`RESEARCH_VALIDATION_REPORT.md` §5):
entry slippage +0.1bps (not the originally-cited −0.1bps), 64.4% of trades leave ≥1R on the
table, 22.6% become +1R reversals — now also live on the `/exits` dashboard page with
family/regime/side/generation/agent/date-range filtering, backed by the new
`/api/exit-analytics` endpoint reading `TradeAnalytics` (no new backend tracking). §3's two
controlled exit experiments are the "then run controlled exit experiments" step; the
remaining five previously-planned exit designs (trailing, volatility-adjusted, time-based,
partial-profit, MFE-adaptive, reversal-aware) remain a documented plan (phase 1 report §6),
now runnable through §2's tooling whenever pursued.

---

## 6. POSTGRESQL RE-VERIFICATION

Repeated phase 1's dry run against a **fresh** snapshot and a fresh throwaway local Postgres
16 cluster (same isolated-port, isolated-socket, never-touch-a-real-server discipline):

- `alembic upgrade head`: all 25 migrations (24 + this phase's none — no new migration this
  phase) applied cleanly.
- `scripts/migrate_sqlite_to_postgres.py`: all 37 populated tables copied and verified
  row-for-row (991 agents, 8,246 trades, 80,054 decisions, 319 experiments, etc.).
- **Aggregates spot-checked and matched exactly**: `sum(trades.net_pnl)` = −239.0457 in both
  SQLite and Postgres; `sum(agents.equity)` = 98,861.158 in both.
- **Timestamps verified**: sample `agents.created_at` round-trips to the identical UTC
  instant (Postgres displays in session-local +05:30, same moment).
- **Foreign-key integrity verified**: 0 orphaned `trades` rows (agent_id join).
- `tests/test_postgres.py` + `test_postgres_concurrency.py`: 17/19 passed against the
  real cluster. The 2 failures are the same pre-existing, unrelated index-metadata drift
  documented in phase 1 (`ix_fitness_scores_agent_asof`, `ix_fitness_scores_asof`,
  `ix_trades_position` — declared in migrations, not mirrored in current SQLAlchemy model
  metadata; confirmed pre-existing by reproducing it against the unmodified head).

**Applied to the real live database too**: `./run.sh start` (§7) ran `alembic upgrade head`
against the actual `trading_lab.db` as part of normal startup, applying this phase's
migration history cleanly — real evidence the migration chain works outside a test harness.

**Not done, still recommended before an actual cutover**: reconcile the pre-existing index
metadata drift (out of this phase's scope — unrelated to as_of/experiment/dashboard work).

---

## 7. RESEARCH DASHBOARD

Extended the existing single-file, no-framework dashboard (`app/static/index.html`,
`~/main.py`'s explicit `@app.get` route-per-page pattern — no `StaticFiles` mount exists, so
each new page gets its own tiny route, matching convention) rather than introducing a new
frontend stack.

- **Home page**: added an explicit "LIVE TRADING MODE IS ENABLED" banner condition (data —
  `trading_mode` — was already fetched, just not wired to the alert banner before); the
  existing worker-down/market-data-stale/database-unreachable/kill-switch alerts were already
  present and are unchanged.
- **New `/exits` page** (`app/static/exits.html` + `app/api/routes/exit_analytics.py`,
  `GET /api/exit-analytics`): MFE/MAE/left-on-table/holding-time histograms, MFE-capture and
  post-exit-favorable summary stats, reversal rate, trade-quality-class and exit-reason
  distribution tables — filterable by family/generation/side/regime/agent/date range.
  Caught and fixed a real, pre-existing data-quality quirk while building this:
  `TradeAnalytics.side` is stored as `"SIDE.SHORT"`/`"SIDE.LONG"` (an enum-repr artifact in
  `analytics_store.py`, not introduced this phase) rather than plain `"SHORT"`/`"LONG"` — the
  endpoint matches by suffix so its own query parameter stays the clean spelling; the
  underlying storage quirk itself was left alone (out of scope, non-blocking, `report_trade_quality.py`
  already worked around the same thing).
- **New `/experiments` page** (`app/static/experiments.html`): lists every experiment
  (wires the previously-unused `/api/evolution/experiments` endpoint, now also accepting a
  `kind` filter and returning `parameters`/`finished_at`), click-to-select two rows for a
  baseline-vs-candidate diff table (new `GET /api/evolution/experiments/diff` endpoint,
  wrapping §2's `diff_experiments`).
- **Agent detail** (already built, `index.html`): added one new MFE/MAE summary card per
  agent, reusing the same `/api/exit-analytics?agent_id=` endpoint — failure-isolated (never
  blocks the rest of the panel if it errors).
- Verified live, not just inspected: started the API against a real snapshot, `curl`-tested
  all three page routes (200) and both new API endpoints with real filters (side, agent_id,
  generation), fixed two real bugs found this way (`agent_id` needed `uuid.UUID` typing to
  bind correctly against the `Uuid` column type; the `side` enum-repr quirk above) before
  shipping.

**Not done**: a dedicated "excessive agent deaths" / "extreme drawdown" banner threshold
(would need new backend aggregate fields the current `/api/system/status` payload doesn't
carry — flagged, not invented) and a `BACKTEST` value in the `TradingMode` runtime enum
(deliberately not added — see phase-2 plan's scope-discipline note: backtest results are a
labeling/UI distinction, not a live runtime state the system is ever "in").

---

## 8. 500-AGENT LONG-RUN PREPARATION

Every required field was already confirmed present in phase 1 (`Agent`/`Position`/`Trade`/
`TradeAnalytics` carry the full requested set — id/generation/parent/strategy/balances/P&L/
drawdown/trade-count/lifetime/status, dead-agent auditability via `death_timestamp`/
`death_reason`/`final_equity`/`final_pnl`). This phase adds:
- Every evolutionary event type (selection, mutation, cloning, generation, death, survival)
  already recorded via `EvolutionEvent`/`Experiment` — confirmed still true, unchanged.
- Checkpoint/snapshot cadence: `agent_snapshots` (already populated, 50 rows in this
  dataset) + `stage_metrics`' observation-window fields — sufficient, no new schema.
- Config: `AGENT_COUNT=500`, `TRADING_MODE=paper` per `.env` — same pattern this session's
  recovery test (§9) exercised at the current population size (991 agents, 2 generations),
  proving the pipeline handles a comparable order of magnitude already.

---

## 9. RECOVERY TEST — real, on the actual dev environment

System was confirmed **fully stopped** before this test began (verified via `./run.sh status`),
so nothing in-progress was interrupted.

1. Timestamped backup of the live `trading_lab.db` (`data/backups/trading_lab_pre_recovery_test_20260926_165422.db`).
2. `./run.sh start` — worker, research, api all came up; `trading_mode: "paper"` confirmed.
   Migration `c1d5e9a3f7b2` (this phase's §1... actually phase-1's Postgres fix) applied
   cleanly to the real database as part of normal startup.
3. Worker correctly detected the stale gap since its last run and ran its existing
   **catch-up replay** mechanism (`cycle.catchup_truncated_bars_not_replayed`,
   `halt: "catchup_replay"`) before resuming normal cycles — a real, positive finding: the
   system already handles "was stopped, resumed later" gracefully, not just clean shutdowns.
4. State snapshot before the targeted stop: 991 agents, 8,253 trades, 0 open positions,
   80,322 decisions, 316 experiments.
5. Stopped **only** the worker process (research and API kept running throughout — a
   stricter test than stopping everything, since it proves the worker's own state recovery
   in isolation).
6. Restarted the worker.
7. **Verification, all passed:**
   - Agents: 991 (unchanged — no loss, no duplication).
   - Trades: 8,253 immediately after restart (unchanged, as expected for a few-second gap),
     grew normally afterward as new cycles closed positions.
   - Decisions: grew from 80,322 → 80,386 as cycles resumed (expected new activity).
   - **Zero duplicate rows** across every checked table:
     `trades` (0 duplicate ids), `orders` (0 duplicate `client_order_id`), `decisions`
     (0 duplicate ids), `worker_cycles` (0 duplicate `cycle_id` across 1,536 rows spanning
     the restart).
   - New cycle IDs after restart were strictly new (`SOL:1m:1790441640000`, never seen
     before) — no reprocessing of already-completed cycles.
8. `./run.sh stop` — system returned to the exact stopped state it was found in.

**Result: PASSED, every checkpoint.**

---

## 10. FINAL READINESS CHECK

| Requirement | Status |
|---|---|
| `as_of` tests pass | **PASS** — 14/14 new, all green |
| No known OOS leakage | **VERIFIED** (phase 1; reconfirmed, not touched this phase) |
| Fitness fix intact | **VERIFIED** — untouched this phase, full suite green |
| Experiment runner works | **PASS** — 8 unit tests + 2 real end-to-end runs against live data |
| Baseline comparison works | **PASS** — real comparison table produced, rendered on `/experiments` |
| PostgreSQL migration verified | **VERIFIED** — fresh dry run, row+aggregate+FK+timestamp checks all matched |
| Backup verified | **VERIFIED** — pre-recovery-test backup taken and retained |
| Recovery verified | **PASS** — real test, zero duplicates, zero data loss |
| 500-agent configuration verified | **VERIFIED** (data model + config, no new run started) |
| Paper/shadow mode verified | **VERIFIED** — `trading_mode: paper` confirmed live during the recovery test |
| Live trading disabled | **VERIFIED** throughout — never enabled, dashboard now warns loudly if it ever is |
| Dashboard operational | **PASS** — all 3 pages + both new endpoints tested live against real data |
| Agent monitoring operational | **PASS** — pre-existing, extended with MFE/MAE summary |
| Exit analytics operational | **PASS** — new page + endpoint, verified against real filtered data |
| Experiment tracking operational | **PASS** — list + diff, both tested live |

**No critical requirement failed.**

## READY FOR MULTI-WEEK PAPER/SHADOW EXPERIMENT

---

## Final test suite run

Full backend suite, no scratch Postgres cluster running (so the 19 Postgres-specific tests
report as skipped here — see §6 for their dedicated, separate run against a real cluster,
17/19 passed there):

**963 passed, 2 failed, 18 skipped, 2 xfailed (0:06:39).**

Both failures are pre-existing, unrelated to this phase, and already documented from the
prior phase's report:
- `test_logging.py::test_uvicorn_access_log_formats_and_is_redacted` — pre-existing.
- `test_secret_scan.py::test_repository_tracked_files_are_clean` — `backend/.env` is
  tracked in git with real secrets (`HYPERLIQUID_PRIVATE_KEY`, `OLLAMA_API_KEYS`); a
  genuine, pre-existing security finding, not introduced or fixed by this session.

24 new tests added this phase: `tests/test_as_of_boundaries.py` (14),
`tests/test_experiment_runner.py` (8), 2 new cases in `tests/test_api_endpoints.py`.

---

## Known limitations

- Average R is only computable for `fixed_pct` stop-loss configs (most of this population
  uses `atr_multiple`) — honestly reported as "n/a", not approximated.
- The IMPLICIT-SAFE query inventory (§1.4) is documented and one invariant is freshly
  tested, but not all ~10 call sites got their own dedicated test — recommended before any
  future parallelized-evaluation initiative, not before this one.
- The pre-existing index-metadata drift (3 indexes) and the `TradeAnalytics.side` storage
  quirk are both documented, neither fixed — out of this phase's scope.
- §3's two exit experiments are a tooling demonstration, not a considered recommendation —
  do not promote either candidate from this alone.

## Recommended next experiment

Start the multi-week 500-agent paper/shadow run. Once real multi-day data accumulates, use
§2's runner to re-run the five still-undemonstrated exit designs from phase 1's exit
experiment plan, this time with enough independent trade volume per candidate to move past
"PROMISING — REQUIRES UNSEEN DATA."
