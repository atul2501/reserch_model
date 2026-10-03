# Pre-Trade Decision Architecture: Audit, Prototype and Shadow Comparison

**Scope.** Research and isolated prototype only.

- Live trading behaviour is unchanged.
- The new package `backend/app/pretrade/` is imported by nothing in the live path, and a test enforces that.
- Data comes from `trading_lab_20261002_162728.dump`, restored to an isolated Postgres instance (127.0.0.1:55432).

**Files**

| File | Content |
|---|---|
| `measure_latency_before.py` | Per-stage latency of the current system |
| `latency_before.csv` | Summary of the above |
| `latency_before_cycles.csv`, `latency_before_orders.csv` | Raw data |
| `bench_fast_path.py` | Fast-path compute benchmark |
| `latency_after_bench_*.csv` | Benchmark output |
| `shadow_replay.py` | Old vs new replay |
| `latency_after.csv`, `decision_freshness.csv`, `price_drift.csv`, `shadow_comparison.csv` | Replay outputs (48,016 candidate signals) |
| `backend/app/pretrade/*` | Prototype |
| `backend/tests/test_pretrade_architecture.py` | 28 tests |

> **Do not read this as a profitability result.** The forensic audit established that the signals have ~0 pre-cost edge against ~13.5 bps of cost. Removing latency cannot change that, and the replay confirms it (Q8).

---

## 1. Current architecture (traced in code)

```
Hyperliquid WS/REST candle  ──>  market_data_service: bar is_final once close + CANDLE_FINALITY_GRACE_MS (1.5 s)
                                     │   worker polls; picks up the confirmed bar
                                     ▼
worker/cycle.py::process_candle(K)
  ├─ compute_features(300 bars ≤ K)                               app/market/feature_engine.py
  ├─ persist MarketFeatureSet + regime
  ├─ IF council_due(K)  (every 5th bar, COUNCIL_INTERVAL_CANDLES=5)
  │     await asyncio.wait_for(run_council_cycle(...), 45 s + grace)   ◄── BLOCKS everything below
  │       └─ 8 analysts in parallel (gpt-oss:120b, Ollama API, 44 s per-analyst timeout)
  │          → consensus → judge if the vote is close → CouncilDecision row
  ├─ verify_candle_final (second gate)
  └─ run_decision_cycle (app/agents/decision_loop.py), for ~500 agents:
        execute PREVIOUS bar's pending entry/exit at bar K's OPEN      (paper next_open)
        manage open position (funding, stop/TP/trailing on bar K OHLC)
        evaluate_signal(DNA, features)  → council.combine (veto / size) → risk engine → sizing
        Order(status=PENDING, requested_price = close K)
  ... 60 s later, cycle K+1: PaperExecutionAdapter fills it at OPEN(K+1) + 2 bps slippage
```

**Two corrections to the task's premise:**

1. **The LLM is not consulted per trade.** It is one market-wide council per 5th bar, computed *before* any strategy runs. On that bar every agent's signal waits for it. On the other 4 of 5 bars no LLM is involved; 82% of entry orders were placed on such bars.
2. **45 s is the configured deadline, not the typical latency.** Measured council latency: p50 8.9 s, p90 13.3 s, p99 19.5 s, max 44.0 s. Only 3 of 1,487 councils took more than 30 s.

### Measured stage latencies

`latency_before.csv`, from wall-clock DB timestamps (Python `utcnow()` at insert, and `worker_cycles` / `council_decisions` wall-clock fields).

| Stage (ms after bar K close unless stated) | Council bar p50 / p90 / p99 / max | Non-council bar p50 / p90 / p99 |
|---|---|---|
| Wait for confirmed bar (1.5 s grace + poll) | 2,398 / 2,720 / 3,077 / 3,331 | 2,404 / 2,750 / 3,180 |
| Feature calculation (duration) | 24 / 34 / 103 / 150 | 24 / 34 / 104 |
| **LLM council (duration)** | **8,861 / 13,302 / 19,474 / 44,007** | — |
| Slowest analyst (duration) | 8,083 / 10,812 / 15,903 / 44,005 | — |
| Strategy + risk → first order (duration) | 292 / 489 / 737 | 306 / 509 / 808 |
| **Decision / order created** | **11,368 / 15,132 / 21,313 / 47,275** | **3,018 / 3,567 / 4,228** |
| Paper fill processed (wall clock, next cycle) | 62,990 / 63,531 / 64,148 | 63,137 / 71,555 / 122,604 |
| Exchange ack / fill | **Not measurable.** Paper mode only; `latency_ms` is a simulated RNG value (p50 149 ms). There is no live venue. | — |

**Paper-fill caveat.** A paper entry is *priced* at OPEN(K+1), which is the price at the instant bar K closes. That is 3 s (normal bars) to 11–47 s (council bars) **before** the decision that "used" it was made. In paper mode the council delay therefore never affected entry prices; in live trading it would. Measured effect: +0.045 bps per trade of paper optimism vs a live order at decision time (t = 1.2); +0.17 bps on council bars.

## 2. New architecture (prototype)

```
confirmed bar K (cutoff = K close)
   └─ features → population indicators → DNA strategy signal        ~257 ms p50 (measured)
        └─ PreTradeDecision (immutable; signal bar, cutoff, reference price, versions)
             └─ DecisionCache (one per agent; invalidates on new bar / age / drift / regime /
                               direction / conditions / risk epoch / position / conflict)
                  └─ ExecutionGate (deterministic, ~2.4 µs per decision)
                       freshness · same signal bar · no look-ahead · price drift · spread · cost ·
                       risk engine verdict · no open position / pending order · no conflict
                          └─ order (immediately)

LLM council ──(background task, never awaited by the execution path)──> CouncilView (time-stamped)
            └─ logged for shadow / research; NOT an execution input (see Q9)
```

**Prototype modules** (`backend/app/pretrade/`):

| Module | What it provides |
|---|---|
| `decision.py` (`PreTradeDecision`) | All required fields. `expected_move_bps`, `horizon_seconds`, `model_version` and `prompt_version` are **None** because nothing in the current system produces them; they are never fabricated. The constructor rejects look-ahead: features or council output dated after the information cutoff. |
| `cache.py` (`DecisionCache`) | Every invalidation reason from section 7 of the task. `get()` never returns a stale or mismatched decision. Decisions are single-use (`consume`). Every invalidation is recorded with its reason. |
| `gate.py` (`ExecutionGate`) | The only component that can authorise execution. Reports **all** failed checks plus non-blocking flags (`cost_check_unavailable`, `spread_not_checked`). Decision age is measured from the **information cutoff**, not from when the record was written. |
| `council_view.py` (`CouncilView`) | Non-blocking: `launch()` never stacks runs behind a slow LLM, `latest()` is an O(1) read that returns None when stale, and failures leave the old snapshot to age out. |
| `latency.py` (`LatencyTrace`) | All 11 stage timestamps from section 11 of the task, plus derived latencies and a monotonicity check. |

**Tests** (`tests/test_pretrade_architecture.py`, 28 passing):

- isolation from the live path;
- information cutoff; look-ahead rejection for features and council;
- no fabricated fields;
- freshness grid; stale signal bar; decision written before bar close; execution before the cutoff;
- drift in both directions; sign of drift;
- risk / position / pending / conflict / spread / cost checks;
- the LLM cannot authorise execution; council age;
- determinism, and a median validation time under 1 ms;
- every cache invalidation reason; conflicting replacement; single use; new-bar sweep;
- non-blocking council view with failure handling;
- latency derivation.

**Generating `expected_move_bps` honestly.** It needs a model whose target is the **signed forward return over a declared horizon**. The current V1 target (`net_pnl > 0`) is not that. The model must be trained walk-forward on decision-time features and calibrated in bps, so that the cost check compares like with like. Phase 1 and 2 found no feature set that predicts this above noise. Until one passes OOS, the field stays None, and the gate either flags the gap (default) or fails closed (`require_expected_move=True`).

**1-minute candle semantics (documented).**

- Bar `09:30:00–09:30:59.999` becomes usable only when it is `is_final`, which happens at 09:31:01.5 at the earliest.
- The decision's `information_cutoff_ms` is 09:30:59.999.
- The gate rejects any decision written before its cutoff, and any execution before the cutoff.
- No strategy uses the forming candle.

## 3. Shadow comparison (historical replay, old vs new)

**Sample:** 48,016 candidate signals, consisting of every entry order (44,557) plus every council veto (3,459).

**What is measured vs modelled:**

- **Measured:** old decision times (per signal), per-cycle confirmed-bar wait, feature time, council timings, and the fast-path compute benchmark on the real generation-6 population (497 DNAs).
- **Modelled:** the sub-minute SOL price. No tick history exists in the backup or the exchange API. It is estimated with a Brownian bridge inside bar K+1 using Parkinson volatility, clamped to the bar's range. In addition, the **exact** bound "guaranteed within tolerance" (bar range relative to the reference price) is reported.
- **No look-ahead:** bar K+1 is used only to evaluate what happened after the decision.

**Not done: a live shadow run.** No live or shadow system was deployed or connected; that remains a later step (section 5).

### Latency (`latency_after.csv`)

| Signal → decision (ms) | Old p50 / p90 / p99 / max | New p50 / p90 / p99 |
|---|---|---|
| Council bars | 11,234 / 15,345 / 21,042 / 47,275 | **2,697 / 3,033 / 3,369** |
| Non-council bars | 3,018 / 3,567 / 4,228 | 2,698 / 3,037 / 3,499 |
| All | 3,173 / 11,709 / 17,817 | 2,698 / 3,036 / 3,450 |

Fast-path compute on this machine: features 23 ms + population indicators 222 ms + 497 strategy evaluations 8 ms + decision records 1 ms + gate 0.3 ms = **257 ms p50 (424 ms p90)**. Gate cost per decision: **2.4 µs**.

**Remaining floor: ~2.4 s of waiting for the confirmed bar** (1.5 s finality grace plus polling). This is now the dominant latency.

### Freshness (`decision_freshness.csv`)

Share of decisions stale at execution:

| MAX_DECISION_AGE | Old, all | Old, council bars | New, all |
|---|--:|--:|--:|
| 1 s | 100% | 100% | 100% (finality floor) |
| 2 s | 100% | 100% | 100% (finality floor) |
| 5 s | 24.3% | **100%** | 0.27% |
| 10 s | 20.0% | 82.5% | 0.27% |
| 15 s | 3.0% | 11.4% | 0.27% |
| 30 s | 0.06% | 0.16% | 0.02% |

The 0.27% that the new path still rejects are cycles delayed by catch-up or replay (up to 42 s).

**Async council attached to the new path (option B).** The freshest *completed* council is older than 60 s for **99.7%** of signals, and older than 300 s for 24%. For a 1-minute strategy an LLM can be fresh or non-blocking, but not both.

### Price drift (`price_drift.csv`)

| MAX_ENTRY_DRIFT | Old reject share (est.) | New reject share (est.) | Exactly guaranteed within tolerance |
|---|--:|--:|--:|
| 2 bps | 31.7% (council bars 43.3%) | 26.7% | 3.6% |
| 5 bps | 6.1% (13.5%) | 3.4% | 23.9% |
| 10 bps | 0.84% (2.6%) | 0.22% | 61.0% |
| 15 bps | 0.17% (0.64%) | 0.01% | 82.5% |
| 20 bps | 0.06% (0.25%) | 0.01% | 92.4% |

Mean |drift|:

| Bars | Old | New |
|---|---|---|
| Council bars | 2.5 bps (p90 5.8) | 1.5 bps (p90 3.3) |
| Non-council bars | 1.6 bps | 1.5 bps |

Signed drift is about 0 (+0.08 old, +0.06 new; positive = moved in the trade's favour). The 2 bps level is about 2 SOL ticks, so it rejects mostly on tick noise and is too tight to be useful.

### Execution and economics

| Metric | Value |
|---|---|
| New vs old live-equivalent entry price, traded signals (n = 43,878) | **+0.022 bps** (cluster t 0.86); council bars +0.094, non-council +0.006 |
| Hypothetical mean net per trade (same exits, entry adjusted, gate 5 s / 10 bps) | **old −13.52 bps → new −13.43 bps** |
| Signals the new gate rejects | 0.5% (actual net of those trades: −24.8 bps) |
| Trade frequency | New takes 99.5% of old trades, plus 3,459 council-vetoed signals (+7.9%) because the LLM no longer gates. Those were never traded; forensic estimate ≈ −9 bps each after cost. |
| Missed trades caused by latency | ≈ 0. Paper pending orders do not expire because of the council (they fill at the next open regardless). |

---

## Answers

**Q1. Exactly where does the delay occur?**
It occurs in `worker/cycle.py::process_candle`: `await asyncio.wait_for(run_council_cycle(...), timeout=council_deadline_seconds + grace)`. It runs on every 5th bar, **before** `run_decision_cycle`, so all ~500 agents wait. Inside it, `council/service.py::_gather_analysts_with_deadline` runs 8 parallel Ollama calls (`gpt-oss:120b`), followed by a judge in 27% of councils. Measured duration: 8.9 s p50, 13.3 s p90, 44 s max; 45 s is the cap.
On every bar there is also a 2.4 s wait for the confirmed bar (`CANDLE_FINALITY_GRACE_MS=1500` plus polling).

**Q2. Can the decision be generated before execution?**
Yes, for the part that matters. The deterministic strategy decision is fully computable from the closed bar in about 0.26 s and can be executed immediately after gate validation.
An LLM decision **cannot** be both pre-computed and fresh for a 1-minute closed-bar strategy. Pre-computing it means using a bar at least 60 s older; 99.7% of signals would see a council older than 60 s.

**Q3. How much latency can realistically be removed?**
On council bars, about 8.5 s at the median (11.2 → 2.7 s, −76%), and up to 44 s worst case (p99 21.0 → 3.4 s). Non-council bars gain only about 0.3 s.
The next floor is the 2.4 s confirmed-bar wait. Taking bar finality from the WebSocket close event instead of a 1.5 s timer could save about 1.5–2 s more, but it must first be validated, because 1% of stored closes already differ from the exchange's final values.

**Q4. How often are current decisions already stale at execution?**
- At a 5 s limit: 24.3% of all candidate decisions, and **100%** of those on council bars.
- At 10 s: 20.0% (82.5% on council bars).
- At 15 s: 3.0%. At 30 s: 0.06%.

**Q5. How often would the new architecture reject stale decisions?**
0.27% at 5–15 s, all from delayed catch-up cycles. At 1–2 s it would reject 100% because of the finality floor, so 1–2 s limits are not usable until bar finality is faster.

**Q6. How much price drift occurs during the council delay?**
On council bars the mean absolute drift is **2.5 bps** (p90 5.8 bps), versus 1.5 bps with the new path. The signed mean is about 0 (+0.26 bps, not significant). This is modelled with the bridge, since no tick data exists.
Exact bound: 58% of council-bar signals could not have drifted more than 10 bps by any path.

**Q7. How much execution improvement does pre-computation give?**
**+0.02 bps per trade** (t 0.86); +0.09 bps on council bars. That is statistically and economically negligible.

**Q8. Does removing the delay improve the strategy's economics?**
**No.** Expectancy goes from −13.52 to −13.43 bps per trade. The losses come from ~0 signal edge against 13.5 bps of cost, not from latency.

**Q9. Should the LLM remain in the critical execution path?**
**No.**
- It is the only source of material latency (8.9 s median, 44 s worst case).
- Its directional calls are 48% accurate (t ≈ 0.3).
- The signals it vetoed went on to *outperform* (+4.6 bps at 30 m, t 0.9).
- It cannot be made both fresh and non-blocking for 1-minute decisions.

Keep it **off** the path: run it asynchronously via `CouncilView`, log its view next to every decision for shadow evaluation, and use it for research, post-trade analysis and strategy discovery. It should re-enter the path only if a pre-registered shadow test shows its calls predict signed forward returns above cost out-of-sample.

**Q10. What exact architecture should be used going forward?**
**Option A (decision immediately after signal formation), with a deterministic gate and no LLM in the path:**

```
confirmed bar (WS close + finality) → features → strategy/quant signal → PreTradeDecision
  → ExecutionGate [age ≤ 5 s*, same signal bar, cutoff respected, |drift| ≤ 10 bps*,
                   existing Risk Engine verdict, no open position / pending order, no conflict,
                   spread check once book data exists, cost check once expected_move_bps exists]
  → order
LLM council → async CouncilView → shadow log only
```

\* These are starting research values, not tuned values. On this sample, 5 s and 10 bps reject only stale catch-up cycles and real outliers (0.5%). Revisit them with live shadow data, not with in-sample P&L.

**Options considered and not chosen:**
- **B (rolling LLM decision):** always stale (Q2).
- **C (fast model):** no fast model has passed OOS (Phase 1). The fast path is the deterministic strategy itself until a model passes the information test.
- **D (two-stage, fast model then LLM confirmation):** reintroduces the blocking LLM for no measured benefit.

**What this architecture does NOT do: make the system profitable.** Its value is that execution becomes fast, deterministic, stale-proof, versioned and fully timestamped. Any future signal, including the microstructure study recommended by the forensic audit, can then be evaluated without a 9–45 s LLM bottleneck or paper fills priced before their decision.

---

## 5. Path to production (not done; requires sign-off)

1. **Live shadow (next step).**
   - Add a `PRETRADE_MODE=off|shadow|on` setting, default `off`.
   - In `shadow` mode, `process_candle` launches the council through `CouncilView` without awaiting it, and runs the fast path plus `ExecutionGate` in parallel with the unchanged old path.
   - Write each candidate's old and new decision, all `LatencyTrace` stamps, gate reasons and the **live mid price at both submission times** to a shadow table or CSV.
   - This replaces the modelled sub-minute drift with real measurements.
   - Requirement: no new orders, positions or balance writes.
2. **Validate** on at least 2 weeks of shadow data:
   - monotonic latency traces;
   - zero cutoff violations;
   - drift and stale-rejection rates;
   - old vs new decision agreement.
3. **Only then** switch `PRETRADE_MODE=on` in paper. Remove the awaited council from `process_candle` and insert `ExecutionGate` between risk approval and `Order` creation in `decision_loop._process_agent_inner`. That change needs its own review and test run.
4. **Separately**, fix the paper-fill optimism: fill at the price at decision time, not at OPEN(K+1). The gap is small (+0.045 bps) but it is a correctness issue.
