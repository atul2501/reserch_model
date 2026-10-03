# PRETRADE_MODE=shadow — Implementation, Cross-Platform Hardening, Paper-Fill Fix

> **This work does not make the system profitable.** Earlier research established ~0 pre-cost edge against ~13.5 bps of cost; removing LLM latency moved historical expectancy only −13.52 → −13.43 bps. This is an execution and reliability change.

**Default behaviour is unchanged:**
- `PRETRADE_MODE=off` is the default.
- `PRETRADE_MODE=on` is **refused** by configuration validation.
- `PAPER_ENTRY_PRICE_SOURCE=next_open` is the default (legacy fill price).

Nothing was deployed, and no production database, EC2 host, Ollama key or live order was touched.

**Files in this folder**

| File | Content |
|---|---|
| `raw/pretrade_shadow_20261003.jsonl` | Raw shadow records |
| `shadow_decisions.csv` | Candidate decisions |
| `shadow_latency.csv` | Latency per stage |
| `shadow_drift.csv` | Price drift and spread |
| `shadow_gate_rejections.csv` | Gate rejections by reason |
| `council_comparison.csv` | LLM council vs strategy |
| `old_vs_new_agreement.json` | Old path vs new path agreement |
| `analyze_shadow.py` | Analysis script |
| `worker_run.log` | Worker log from the measured run |

---

# MASTER TASK UPDATE (2026-10-03): Pre-Trade Shadow + Profitability Research System

> **Deployment label: READY FOR MORE SHADOW.**
>
> No result in this repository supports calling the system profitable. **No cost-adjusted, out-of-sample edge has been found.** `PRETRADE_MODE=shadow` remains the operating mode, and `PRETRADE_MODE=on` is still refused by configuration validation.

**Companion documents:**
- `PROFITABILITY_RESEARCH_PLAN.md`: the research framework, what failed, the next experiment.
- `DASHBOARD.md`: `/pretrade-shadow` and `/research-lab`.

## M1. Funding-hour production bug: FIXED (paper path, minimal change)

**Change** (`app/agents/decision_loop.py::_fill_entry`):
1. Construct `Position(..., funding_accrued=0.0)`.
2. Call `await db.flush()` right after `db.add(position)`.

**Why both are needed.** The bug had two layers, and the second appeared only after the first was fixed. On a funding-settlement bar, `_accrue_funding` ran on the new position in the same cycle and failed twice:
- `None += payment` raised a TypeError, because the column default is applied only at INSERT.
- It then failed a NOT NULL check on `FundingPayment.position_id`, because the position had no id before a flush.

The agent's savepoint rolled back, and the order expired.

**Production evidence:** 0 of 43,881 positions opened on an hour bar, and all 397 :59 signals ended `expired_unfilled`.

**Regression tests:** `tests/test_funding_hour_entry.py`, 3 tests.

| Test | What it proves |
|---|---|
| The fixture puts a funding settlement exactly on the `:00` bar | The test setup reproduces the production condition |
| `:59` signal → `:00` fill | The order is FILLED; the position exists with entry candle = the hour bar; a FundingPayment is recorded for the new position and equals `funding_accrued`; the existing holder is charged once |
| A non-funding-bar entry is unchanged | Normal entries behave as before |

The tests reproduce the production condition: funding rates are only loaded when *another* agent already holds a position. **Without the fix, the `:59 → :00` test fails** (the order stays PENDING).

**Regression check:** the paper/parity/characterization group passes (235 passed, 2 xfailed). Strategy logic was not touched.

## M2. Architecture isolation (verified)

**Shadow cannot create, modify or close orders or positions, or change balances, equity, P&L, risk, strategy parameters, fitness or evolution:**
- It has no execution engine.
- It uses a separate session with a DB-enforced read-only transaction (Postgres `SET TRANSACTION READ ONLY`, SQLite `query_only`), which is never committed.
- Only plain values leave that session.
- There is an OFF-vs-SHADOW state-equality test.
- The preflight's check 5 proves the read-only refusal against the *real* database before a run.

**Paper trading is unaffected by shadow.** Paper behaviour changed only through the M1 funding fix, which is a bug fix for entries that were being lost; it does not change any strategy.

**The LLM is non-authoritative.** Shadow only records the council result the existing path already produced (`CouncilView.publish`; the LLM is never called twice). On the dashboard, `J_llm.authority` is always "NONE", and LLM VALUE stays NONE until a pre-registered comparison with n ≥ 100 per arm shows it.

## M3. Signal edge evidence: none

**Shadow smoke run** (41 bars on 2026-10-03; 1,979 candidates; exported with the new `export_pretrade_shadow`):

| Metric | Value |
|---|---|
| Measured round-trip cost (282 paper trades) | **14.1 bps** (fees 8.79 + slippage 5.32) |
| Gate-pass candidates, 10 min, gross | **−6.55 bps** |
| Gate-pass candidates, 10 min, **net** | **−20.66 bps** |
| MFE30 / MAE30 | 13.1 / −20.0 bps (adverse excursion dominates) |
| Paper realised net (same period) | −15.8 bps per trade |
| LLM value | INSUFFICIENT DATA |
| Warnings | SINGLE WINDOW, TOO FEW INDEPENDENT TIME BLOCKS (no t-stat or CI shown) |

This is one ~40-minute window, so it proves only that the pipeline works, not anything about the edge. It is consistent with the 25 days of prior research: ~0 bps signal edge against ~14 bps cost.

## M4. Economics

**Does any candidate survive costs? No.**
- Every seeded experiment and the smoke shadow run are net-negative.
- The best gross effect ever found was the BTC 1-minute residual lead (+0.7–0.9 bps): **WEAK EDGE**, about 15× too small to pay costs.
- The cost floor (taker fee + slippage ≈ 14 bps) is the binding constraint. The edge has to beat it, or execution has to change (maker fills, whose fill rate is unmeasured).

## M5. Models tested and failed

There are 31 registry seeds; see `PROFITABILITY_RESEARCH_PLAN.md` section 3. They cover:
- logistic, random forest, hist-gradient-boosting and XGBoost entry filters;
- every strategy signal at 1–60 min holds;
- move, confidence and cooldown filters;
- 40 structural combinations;
- the order-flow proxy;
- exit grids;
- a 16k-rule walk-forward search;
- the LLM council (48% accuracy);
- the BTC 1m lead;
- latency removal.

**Each one is refused if re-proposed.**

## M6. Missing information

What the system lacks, all of it obtainable in real time:
- top-of-book imbalance and microprice;
- aggressor-side trade flow and intensity;
- spread dynamics;
- seconds-level BTC moves;
- maker fill-rate data.

The collector (`scripts/collect_microstructure.py`) now records SOL/BTC trades, BBO and SOL l2Book from the public WebSocket. It ran here from 03:31 UTC with 0 reconnects.

**Book timestamps.** WebSocket BBO arrives ~220–250 ms after its exchange timestamp. The REST `l2Book` timestamp lagged 0.6–2.4 s on the same clock, so the REST snapshot itself is stale; this is not clock skew. Prefer WebSocket BBO, and do not treat the REST timestamp as authoritative unless preflight check 9 shows < 1 s.

## M7. Single next experiment

**Collect ≥ 7 days of microstructure, then run `H1-MICRO-1M`** (the proposer returns exactly this).

H1 was run on ~13 minutes of data as a pipeline check. It correctly returned **NEEDS_MORE_DATA**, not a rejection.

## M8. EC2 shadow run: preflight and 14-day plan

**Preflight:** `python -m scripts.pretrade_preflight --backup-dir <pg_dump dir> --days 14`, run on the host in the worker's environment. Exit code 1 means **do not start**.

| # | Check | PASS condition |
|---|---|---|
| 1 | Clock | SNTP \|offset\| < 100 ms (or WS BBO lag 0–1000 ms if SNTP is blocked); install chrony |
| 2 | Backup | newest dump < 26 h old, non-empty; **take a fresh `pg_dump` first** |
| 3 | Mode | `TRADING_MODE=paper`, `PRETRADE_MODE=shadow` |
| 4 | No live orders | live gates closed; execution venue PAPER |
| 5 | No balance writes | the shadow transaction refuses an UPDATE on the real DB |
| 6 | Shadow dir / disk | writable; free disk ≥ 2 × the estimated 14-day volume (~150 MB/day uncompressed) |
| 7 | Logging | level/JSON set; watch for `pretrade_shadow.cycle_failed` |
| 8 | Council / Ollama | WARN by design: decide deliberately whether to enable the council with production keys (rate limits) |
| 9 | Book source | REST l2Book lag < 1 s, otherwise note it; WebSocket BBO preferred |
| 10 | Microstructure dir | writable |

Local result: **READY FOR SHADOW RUN, 0 FAIL / 1 WARN (council)**; WS BBO 220 ms, REST l2Book 592 ms, check 5 PASS on PostgreSQL.

**14-day run:**
1. Deploy the fix (M1) and this code to EC2 by a **manual, reviewed** deploy; nothing deploys automatically.
2. Worker: `TRADING_MODE=paper PRETRADE_MODE=shadow` (`PAPER_ENTRY_PRICE_SOURCE` left at its default `next_open`).
3. Collector: `python -m scripts.collect_microstructure` as a **separate** systemd service (restart=always). It needs no DB and no keys.
4. Daily: open `/pretrade-shadow` (Daily table, section A missed cycles), `/research-lab` (data sufficiency), and check disk.
5. Day 7+: `python -m scripts.edge_research propose` → `run H1-MICRO-1M` (then H2 and H3 as the proposer allows).
6. Day 14: `python -m scripts.export_pretrade_shadow` → `reports/pretrade_shadow/`; write up results against the objective gate.

**Stop conditions:** any order or position attributable to shadow; a read-only violation; a sustained `cycle_failed`; disk under 2 days of headroom.

## M9. Entry Quality V1

Entry Quality V1 is a frozen historical research baseline and is not in the execution path. It is seeded as `SEED-EQ-V1` (OOS_FAILED). The archival steps are in `PROFITABILITY_RESEARCH_PLAN.md` section 7; nothing was deleted.

## M10. Test results (master task; Windows 11, Python 3.10.11)

| Run | Result |
|---|---|
| Full deterministic suite (`pytest`) | **1,121 passed, 2 failed, 11 skipped (Node.js absent), 2 xfailed**, 4 deselected (performance); 20.6 min |
| ↳ `test_config_audit::test_no_module_reads_the_environment_directly` | **Caused by this task.** The new registry read `EDGE_REGISTRY_PATH` with `os.environ`. **Fixed:** it is now the Settings field `edge_registry_path` (same env var). Re-run: config audit + edge research + dashboard, **41 passed**. |
| ↳ `test_evolution_pipeline::test_orphaned_mid_pipeline_candidates_are_revisited_every_cycle` | **Pre-existing, flaky, unrelated.** It fails 2 of 3 runs on a **clean `HEAD` checkout** with the same assertion (`'champion_comparison' == 'rejected'`), and 2 of 3 with this work. Not platform-specific; needs no external service. Evolution code is out of scope ("do not modify evolution"), so it was **not fixed**. Track it separately. |
| New tests | `test_funding_hour_entry.py` 3, `test_edge_research.py` 20, `test_pretrade_dashboard.py` 15 (+ API), all passing |

## Answers (master task)

| Question | Answer |
|---|---|
| Is the pre-trade path isolated from paper/live? | **Yes** (M2) |
| Is there a signal edge? | **No evidence of one** (M3) |
| Does anything survive costs? | **No** (M4) |
| Which models were tested and failed? | 31 seeded experiments (M5) |
| What information is missing? | Microstructure, seconds-level BTC, maker fill data (M6) |
| Single next experiment | ≥ 7 days microstructure → H1-MICRO-1M (M7) |
| Deployment | **READY FOR MORE SHADOW** |


---

# Previous task: shadow implementation (2026-10-03, earlier)

## 1. Implementation summary

| Change | File(s) | Behaviour with defaults |
|---|---|---|
| New settings: `PRETRADE_MODE` (off\|shadow; `on` refused), `PRETRADE_MAX_DECISION_AGE_SECONDS=5`, `PRETRADE_MAX_ENTRY_DRIFT_BPS=10`, `PRETRADE_SHADOW_DIR=data/shadow`, `PRETRADE_SHADOW_BOOK_TIMEOUT_SECONDS=1.5`, `PRETRADE_SHADOW_TIMEOUT_SECONDS=10`, `PAPER_ENTRY_PRICE_SOURCE` | `app/core/config.py` | none |
| Shadow engine: read-only session, pure strategy/risk/gate evaluation, real best bid/ask from the public `l2Book` read, JSON-lines recorder, old-path price point | `app/pretrade/shadow.py` (new) | not imported |
| `CouncilView.publish()` / `latest_any()`: the existing path's council result is shared, never re-requested | `app/pretrade/council_view.py` | not imported |
| Worker hooks, all behind `pretrade_mode == "shadow"`: (1) shadow step right after features, **before** the council; (2) publish the council result; (3) record the price when the existing path finishes. Lazy imports, try/except, hard timeout. | `app/worker/cycle.py` | two `time.time_ns()` calls only |
| Paper fill: `first_observed_after_decision` option | `app/agents/decision_loop.py`, `app/execution/price_observation.py` (new) | identical (`next_open`) |
| Bug fixes found while hardening tests (section 3) | `config.py`, `ollama_client.py`, `research/registry.py`, `scripts/run_research.py` | see section 3 |
| Test categories, CI matrix, TESTING.md | `pytest.ini`, `tests/conftest.py`, `.github/workflows/ci.yml`, `TESTING.md` | — |

**Not implemented: `PRETRADE_MODE=on`.**
- Settings validation rejects it with "requires a separate review".
- There is no code path that lets the pre-trade decision create an order.

## 2. Safety: how shadow mode is prevented from placing orders

Seven independent layers, each tested.

1. **No execution engine.** `app/pretrade/shadow.py` never imports or calls an `ExecutionEngine`. It only calls pure functions (`evaluate_signal`, `requested_notional`, `margin_state`, `check_trade`, `ExecutionGate.validate`).
2. **Database-enforced read-only.**
   - The shadow step uses its own `AsyncSession` (never the worker's), opened in a `SET TRANSACTION READ ONLY` transaction on PostgreSQL or with `PRAGMA query_only=ON` on SQLite.
   - It is never committed, and is always rolled back and closed.
   - `test_shadow_transaction_is_read_only_at_the_database_level` proves that a balance write inside it is **refused by the database**, and that the pooled connection is writable again afterwards.
3. **No ORM objects leave that session.** Only plain values (ids, numbers) escape. This prevents stale objects from reaching the existing path through a shared identity map, which matters because the worker uses `expire_on_commit=False`.
4. **Whole-cycle equivalence.** `test_shadow_mode_leaves_the_existing_path_identical_to_off` runs the real worker cycle twice on identical fixtures (OFF, then SHADOW) across a decide bar and a fill bar. It asserts **identical** orders, positions, decisions, trades and agent balance/equity/trade counts/cooldowns, and that both runs really traded.
5. **No state change.** `test_shadow_mode_creates_no_order_position_or_state_change` compares the full DB state before and after a shadow cycle: equal, with 0 orders and 0 positions.
6. **Failure isolation.** The hooks catch every exception and enforce `PRETRADE_SHADOW_TIMEOUT_SECONDS`. A shadow failure is logged and counted (`pretrade_shadow_failures`), and the existing path continues.
7. **Live run evidence.** 1,979 shadow records over 41 live bars, every one with `orders_created = 0`, and **0** `pretrade_shadow.cycle_failed` events.

**The LLM is non-authoritative.**
- The shadow path passes `council_trade_allowed=True` to the risk check.
- The council is only *recorded* (`council_*`, `llm_would_veto`, `llm_agrees`).
- `test_llm_is_recorded_but_never_authorises_or_vetoes` publishes an opposed council at confidence 0.99. Every candidate is still gate-allowed, and the veto is only recorded.

**One disclosed side effect on the existing path's timing.** The shadow step runs before the existing path's council and decisions on each bar, so it delays them by its own duration. Measured overhead: features→signal 207 ms + decision 21 ms + order-book read 159 ms ≈ **0.4 s per bar**. Paper fills are unaffected, because they are priced at the next bar's open.

## 3. Cross-platform fixes

Every failure in the original Windows run (1,053 passed / 9 failed / 1 error) was traced to its root cause. **Most were not Windows problems.**

| Test | Root cause (proven) | Platform-specific? | Fix |
|---|---|---|---|
| `test_db_location::test_absolute_memory_and_other_urls_are_untouched` | **Code bug.** `resolve_sqlite_url` re-rendered absolute paths through `str(Path)`, turning `/` into `\` on Windows and violating its own "returned unchanged" contract. | Manifests only on Windows; the contract bug exists everywhere. | Absolute URLs are returned unchanged (`config.py`). |
| `test_no_live_orders::test_every_http_post_...` | **Test bug.** It compared `str(relative_path)` (`app\market\...` on Windows) with `"app/market/..."`. | Yes (Windows). | `Path.as_posix()`. |
| `test_paper_execution_v2::test_paper_and_shadow_adapters_never_touch_the_network` (error at teardown) | **Test bug.** It patched *every* `socket.connect`. On Windows, asyncio's `ProactorEventLoop` builds its self-pipe with `socket.socketpair()`, which is a 127.0.0.1 TCP connect, so loop teardown failed with `_ssock`. | Yes (Windows event loop). | Block **non-loopback** destinations only, plus a new in-test assertion that an external address (TEST-NET-3) is still refused. Not weakened. |
| `test_ollama_client::test_429_is_retried_...` | **Code bug.** With no API keys (keyless Ollama), `_retryable_error` used `any([])`, which is `False`, so a 429 was **never retried**. | **No.** Fails on Linux too. | Keyless client → plain backoff retry. Keyed behaviour (production) unchanged. |
| `test_ollama_client::test_401_on_one_key_...`, `test_401_on_every_key_...` | **Test/implementation drift.** The tests set `client._api_keys` after construction, but per-key health state is built in `__init__`, so every key looked unavailable. | **No.** | Keys configured through Settings (`OLLAMA_API_KEYS`), the production path. Assertions unchanged. |
| `test_entry_quality_audit::test_api_export_csv_endpoint` (and its sibling API tests) | **Test bug.** The fixture never authenticated, while `/api/*` correctly requires auth by default (fail-closed), so it got 401. | **No.** | Fixture authenticates with a viewer key, the same pattern as `test_api_endpoints.py`. A new test asserts that an unauthenticated request still gets **401**. |
| `test_research_event_loop` (×2 failing, timing) | **Real bug plus a fragile test.** (a) `code_version()` spawned 2 blocking `git` subprocesses on **every** call, from async research code on the event loop (`evaluate_oos_once` calls it twice). (b) The first `schema_version()` parses every Alembic migration on the loop. Located with asyncio's slow-callback debugger (0.31 s stall). | The stall is visible on Windows (slow process creation) but the blocking exists everywhere. | (a) Git revision cached per process. (b) `warm_provenance_cache()` at research start-up. (c) Correctness now proven deterministically with `OffLoopProbe`, a thread handshake that *cannot* pass if the work runs on the loop (and a self-test proves the probe fails when it should). The wall-clock versions are kept as opt-in `performance` tests with the **unchanged 0.35 s threshold**; they now pass 3/3 on this Windows machine (previously 0.35–0.50 s stalls). |
| Database "locked" (seen during development only) | Two pytest runs shared `data/test_trading_lab.db`. | No. | Documented in TESTING.md: use a separate `DATABASE_URL` for concurrent runs. |

**Classification:**

| Category | Meaning |
|---|---|
| `unit` | Default |
| `shadow` | Pre-trade tests; deterministic |
| `integration` | PostgreSQL / Node; skips itself when absent |
| `performance` | Opt-in |
| `external` | Opt-in; currently no tests |

The default run, `-m "not external and not performance"`, needs no Ollama, internet, Hyperliquid, AWS, credentials or production database.

**CI** now adds a Windows and macOS matrix job running the deterministic suite. On Ubuntu it keeps the PostgreSQL job and adds an informational performance step. See `TESTING.md` for exact commands per OS.

## 4. Paper-fill fix: before vs after

| | `next_open` (default, legacy) | `first_observed_after_decision` (new option) |
|---|---|---|
| Entry reference price | OPEN of the bar after the signal | First **actually observed** price with timestamp ≥ the decision's wall clock. With 1m OHLCV this is the fill bar's **CLOSE**; high/low have no timestamp and are never used. |
| Price timestamp vs decision | **Before** the decision (the cycle decides 3–47 s after the bar opens) | **≥ decision**. Tested: `entry_price_ts_ms >= decided_at_ms`, `filled_at >= created_at`, `opened_at >= created_at`. |
| Position management | Starts on the fill bar | Starts on the **next** bar (no stop/TP on prices before the fill) |
| No observed price after the decision (late catch-up) | (would fill in the past) | Order **CANCELLED** `no_observed_price_after_decision`. No fabricated price. |
| Modelled prices | none | none (`PriceObservation.modelled` must be False) |

**Why it is not the default.**
- With only 1m OHLCV, the honest "after-decision" price is up to ~57 s *later* than the decision. That is conservative rather than exact.
- Switching it changes paper results and would break paper/backtest parity unless `backtesting/engine.py` changes in lockstep.
- The faithful fix is a real book price at decision time. Shadow mode now records exactly that (`price_at_shadow_execution_point`, real l2Book mid).
- Enable it with `PAPER_ENTRY_PRICE_SOURCE=first_observed_after_decision` after review.

## 5. Test results (this Windows machine, Python 3.10.11)

See section 5a at the end, filled in after the final run.

New and changed test files:

| File | Tests | Result |
|---|---|---|
| `test_pretrade_shadow.py` | the 10 required properties plus extras | 21 passed |
| `test_pretrade_architecture.py` | prototype plus isolation, including a subprocess check that OFF never loads `app.pretrade` | 29 passed |

## 6. Shadow architecture (actual execution flow)

```
confirmed bar K closes ─► worker picks it up (finality grace 1.5 s + REST/WS sync)
  process_candle(K)
   ├─ compute_features ─► persist + commit
   ├─ [shadow] run_shadow_cycle  (own READ-ONLY transaction; ≤10 s; failures swallowed)
   │     population indicators ─► evaluate_signal ×500 ─► pure risk check ─► PreTradeDecision
   │     ─► public l2Book read (best bid/ask) ─► ExecutionGate ─► JSONL record (would_trade / reasons)
   │     reads CouncilView.latest_any()  → recorded only
   ├─ (existing path, unchanged) council if due ─► [shadow] CouncilView.publish(result)
   ├─ (existing path, unchanged) run_decision_cycle ─► paper orders/fills as before
   └─ [shadow] record_old_path_point: l2Book price when the existing path finished
```

## 7–9. Live measurements

**The run.** A local, isolated validation run of the **real worker**:
- live Hyperliquid public market data;
- real features and strategies, 500 bootstrapped agents;
- `TRADING_MODE=paper`, `PRETRADE_MODE=shadow`;
- scratch PostgreSQL DB `shadow_smoke` on a throwaway cluster;
- **council disabled**, so the production Ollama keys and their rate limits were never touched (see section 10).

**Window:** 41 bars, 2026-10-03 01:36 → 02:17 UTC.

**Not a 2-week shadow run**, and not production: it validates the mechanism and gives first real numbers. The first bar includes the cold-start history sync and is excluded from steady-state stats (32 s there, all candidates correctly rejected as stale).

### 7. Latency (steady state, 40 bars; `shadow_latency.csv`)

| Stage | p50 | p90 | max |
|---|--:|--:|--:|
| Bar close → features start (finality grace + candle sync) | 2,818 ms | 3,194 | 3,518 |
| Feature calculation | 43 ms | 59 | 99 |
| Features → signals (population indicators + 500 strategies) | 207 ms | 358 | 415 |
| Signals → decision records | 21 ms | 38 | 59 |
| **Bar close → decision ready (signal-to-decision)** | **3,136 ms** | 3,579 | 3,991 |
| **Decision → shadow execution point** (incl. l2Book read) | **159 ms** | 181 | 283 |
| Gate validation per decision | **7.1 µs** | 8.8 µs | 32.9 µs |
| Decision age at the gate (new path) | 3,384 ms | 3,789 | 4,229 |
| Old path decision age, same agent and bar (council off; includes the ~0.4 s shadow overhead) | 4,017 ms | 5,064 | 6,081 |

**The dominant remaining latency is the ~2.8 s wait for a confirmed bar**, not computation. LLM council latency is not in this run; the historical value is 8.9 s p50, 44 s max.

### 8. Decision freshness

- **Stale rejections (age > 5 s), steady state: 0 of 1,967 (0%).**
- Cold-start bar: 12 of 12 rejected (33 s old). The guard works.

Gate outcomes (`shadow_gate_rejections.csv`, 1,967 candidates):

| Outcome | Count | Share |
|---|--:|--:|
| would trade | 315 | 16.0% |
| risk rejected | 1,514 | 77.0% |
| ↳ below minimum order notional | 839 | 42.7% |
| ↳ duplicate position | 571 | 29.0% |
| ↳ cooldown active | 104 | 5.3% |
| position already open | 571 | 29.0% |
| order already pending | 140 | 7.1% |
| stale / wrong bar / price drift / conflict | 0 | 0% |

**Old vs new on the same bars and agents (`old_vs_new_agreement.json`):**
- Same direction in **100%** of the 1,265 overlaps.
- Both trade: 315.
- New trades but old doesn't: 0.
- Old ordered but new rejected: **2 (0.1%)**. Both are caused by **state-snapshot timing**: the shadow step reads state before the existing path processes the bar's own fills and exits (a pending order that did not fill; a position stopped out on that bar). **Design requirement for any future `on` mode: the gate must run after position management for the bar.**

### 9. Price drift (real best bid/ask; `shadow_drift.csv`)

Sign convention: **positive = price moved in the trade's favour** (up for LONG, down for SHORT) between the signal-bar close and the shadow execution point.

| Metric | Value |
|---|--:|
| Signed drift: mean / p50 / range | −0.19 / −0.42 / ±2.93 bps |
| Absolute drift: mean / p90 / max | **0.65 / 2.10 / 2.93 bps** |
| Spread: median / max | **0.84 / 1.68 bps** (one tick ≈ 0.84 bps at $119) |
| Would reject at 2 / 5 / 10 bps | 10.1% / 0% / 0% |
| Old-path price vs new decision price (same bar, signed) | +0.13 bps mean (the old path pays slightly more), \|mean\| 0.15 bps |
| **l2Book `time` lag vs receipt** | **p50 2.36 s, max 3.07 s** |

**Finding: the REST `l2Book` snapshot timestamp lags receipt by ~2.4 s on 100% of reads.**
- So no book price is timestamped *after* the decision, and every `shadow_fill_source` is honestly `no_observed_price_after_decision`.
- The lag is either a cached snapshot or clock skew between this PC and the exchange. With this data the two cannot be told apart.
- **Before relying on book prices for fills:** run on EC2 with NTP, and/or use the WebSocket `l2Book`/`bbo` stream.

## 10. LLM comparison (`council_comparison.csv`)

The live run had the council **disabled**, so this uses the **real council history** in the production backup (8,284 traded signals on council bars; 45,932 traded signals overall).

| View | Council NEUTRAL | Disagrees with the quant direction (of its directional calls) | Disagrees (of all) | Would veto (opposed, conf ≥ 0.60) | Council age p50 |
|---|--:|--:|--:|--:|--:|
| Same-bar council (old path, waited 8.9 s for it) | 23.8% | **38.5%** | 29.3% | 0%\* | same bar |
| Async: freshest council at the new decision time | 40.8% | **57.5%** | 34.0% | 15.3% | **183 s** |

\* Signals the same-bar council vetoed never became orders, so they are not in this traded set.

Its historical directional accuracy is 48% (forensic audit). Made asynchronous, it is about 3 minutes old and disagrees more often than it agrees. **Recommendation unchanged: keep the LLM out of the execution path. Record it in shadow only.**

## 11. Remaining risks and pre-existing bugs found

1. **PRE-EXISTING PRODUCTION BUG: every entry that fills on a funding-hour bar is lost.** It reproduced live in this run, so this is not shadow-related.
   - **Mechanism:** a position created in `_fill_entry` and managed in the same cycle has `funding_accrued = None`, because the model's `default=0.0` is only applied at INSERT. `_accrue_funding` then raises `None += float`, the agent's savepoint rolls back (losing the fill), and the order expires.
   - **Production evidence:** 0 of 43,881 positions opened on an hour bar; **all 397** entries signalled at minute :59 ended `CANCELLED/expired_unfilled`.
   - **FIXED in the master task (section M1):** `funding_accrued=0.0` plus `db.flush()`, with regression tests.
2. **Gate placement.** The 0.1% old/new disagreement shows that an `on` mode must evaluate after the bar's position management.
3. **Book timestamps.** Resolve the ~2.4 s `l2Book` time lag (NTP / WebSocket) before using book prices for fill simulation.
4. **Shadow overhead.** ~0.4 s added to the existing path per bar in shadow mode. Measure this on EC2.
5. **Coverage gaps.**
   - Live LLM-council shadow data was not collected. Enable the council in the EC2 shadow run (that uses the production keys, so it should be a deliberate choice).
   - macOS was not run locally; the CI matrix covers it on the next push.
6. **The finality floor** (~2.8 s) now dominates latency.

## 12. Production readiness

**READY FOR SHADOW.**
- Not ready for paper with `PRETRADE_MODE=on`; that mode does not exist and is refused.
- Not production-ready.

The shadow run should go on EC2 with NTP. Fix the funding-hour bug first or alongside, since it distorts the existing path that shadow compares against.

## Answers

| # | Question | Answer |
|---|---|---|
| Q1 | Zero orders in shadow mode? | **Yes.** Proven by design (no execution engine), a DB-enforced read-only transaction, the OFF-vs-SHADOW equivalence test, and 1,979 live records with `orders_created=0`. |
| Q2 | Zero position changes? | **Yes.** Same proofs; the state-equality test covers positions. |
| Q3 | Zero balance changes? | **Yes.** A balance write inside the shadow transaction is refused by the database (tested); balances are equal in OFF vs SHADOW. |
| Q4 | Can the LLM block the deterministic path? | **No.** Shadow runs before the council; tested with a slow council (all 3 shadow decisions existed before the LLM started). Note that the *existing* path still waits for its council, which is unchanged by design. |
| Q5 | Actual signal-to-decision latency? | **3.14 s p50, 3.58 s p90, 3.99 s max** (bar close → decision), of which ~2.8 s is the confirmed-bar wait. |
| Q6 | Actual decision-to-shadow-execution latency? | **159 ms p50, 181 ms p90, 283 ms max** (dominated by the public l2Book read). Gate validation alone: 7 µs. |
| Q7 | Actual price drift? | **\|drift\| 0.65 bps mean, 2.10 bps p90, 2.93 bps max**; signed −0.19 bps; spread 0.84 bps median. |
| Q8 | How often rejected as stale? | **0% in steady state** (0/1,967); 100% on the cold-start bar (33 s old), as intended. |
| Q9 | How often does the LLM disagree? | **38.5%** of its directional calls when same-bar (old path); **57.5%** when used asynchronously (183 s old). Historical backup data; live council was off. |
| Q10 | Does the paper fill now happen after the decision? | **With `PAPER_ENTRY_PRICE_SOURCE=first_observed_after_decision`: yes** (price and fill timestamp ≥ decision; tested). **The default is still the legacy `next_open`**, whose price predates the decision; switching needs a backtest-parity change and review. |
| Q11 | Deterministic suite passes without Ollama/credentials/network? | Yes. Ollama/Hyperliquid are mocked; the network guard blocks non-loopback connects; final numbers in section 5a. |
| Q12 | Windows, macOS and Linux? | **Windows: run here (section 5a).** Linux: the existing Ubuntu CI job. **macOS: not run locally**; the new CI matrix job (windows-latest, macos-latest) proves it on the next push. Every failure found was fixed at its root cause. |
| Q13 | Remaining failures? | See section 5a. |
| Q14 | Ready for a 2-week live shadow run? | **Yes, for shadow only, on EC2.** Preconditions: NTP-synced clock, a deliberate decision on enabling the council (production Ollama keys), and fixing (or at least tracking) the funding-hour entry bug. |

---

## 5a. Final test results (Windows 11, Python 3.10.11, this machine)

| Run | Result |
|---|---|
| **Before this task** | 1,053 passed, **9 failed, 1 error**, 11 skipped |
| **Full deterministic suite after this task** (`pytest`) | **1,084 passed, 1 failed, 11 skipped, 2 xfailed**, 4 deselected (performance); 39 min |
| ↳ the 1 failure | `test_dna_runtime_coverage`. **Cause:** a Python **3.10** quirk, not an OS issue: `isinstance(list[X], type)` is `True` on 3.10 (fixed in 3.11), so `issubclass()` raised. It passed in CI because CI uses 3.11. **Fixed** in the test with `typing.get_origin()`, and its file re-run gives **6 passed**. Not related to this work. |
| Shadow category (`-m shadow`) | **50 passed** |
| Paper execution + previously failing files | **50 passed** |
| Performance (`-m performance`, unchanged 0.35 s threshold) | **4 passed** (3/3 repeated runs earlier) |
| Integration: PostgreSQL | Ran against a local PostgreSQL 16 and passed |
| Integration: Node.js | 11 skipped (Node.js not installed here) |

**Remaining failures: none known on this machine.**
- The whole suite was not re-run end to end after the last one-line test fix (39 min). That fix's file and every changed category were re-run and pass.
- **macOS** has not been executed; the new CI matrix job is the proof.
- **Linux** is covered by the existing Ubuntu CI job, which now also runs the opt-in performance tests as informational.
