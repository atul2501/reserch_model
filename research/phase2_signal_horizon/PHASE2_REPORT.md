# Phase 2 — Signal Horizon, Costs and Edge Search

**Backup:** `trading_lab_20261002_162728.dump`. It was restored into an isolated, throwaway Postgres 16 cluster (127.0.0.1:55432, db `trading_lab_research_20261002`).
**Scope:** research only. The production DB, EC2, live logic, V1 and the config were not touched.

## Executive Summary

**No deployable edge found.**

- **Horizon.** The existing signals have no directional edge at any horizon from 1 to 60 minutes.
  - All 17,935 unique signals: mean signed forward return is −0.02 bps at 1m, −0.28 at 10m, +0.90 at 30m and +1.72 at 60m.
  - Cluster t-stat is ≤ 1.73 at every horizon.
  - Directional accuracy is 47–50%.
  - Realistic round-trip cost is ~13.5 bps.
  - Longer horizons only widen the spread of outcomes. The mean stays near zero, so cost drag never shrinks below about 12 bps per trade.
- **Entries are indistinguishable from random direction.** The excursion-class mix of the actual entries matches that of the same trades flipped to the opposite side.
- **Walk-forward selection fails.** It searched ~16k pre-registered rules per fold (strategy × horizon × minimum move × confidence × cooldown, plus 12 bar-level order-flow variants). The rules picked on validation produced −21.4 bps per signal on OOS at realistic cost. Only 1 of 3 OOS windows was positive, and a different rule won each fold.
- **The one prior lead does not hold.** Order flow held 60m (flagged in Phase 1) is negative in 2 of 3 OOS windows at realistic cost.
- **What the signals actually do.** At mid prices they break even (+0.08 bps per trade, PF 1.009). The ~13.5 bps of fees and slippage then make every configuration lose.

**Production recommendation: A. KEEP CURRENT SYSTEM.** No sufficiently strong edge was found, so nothing new should go to paper or production.

## Data Integrity

All of these anomalies exist in the backup, which is a fixed snapshot.

| Anomaly | Count | Cause | Status in current code | Research impact |
|---|---|---|---|---|
| Rollover settled at stale price 123.36 | 202 trades (rollovers 09-28 00:38 ×7, 09-29 00:40 ×89, 09-30 00:42 ×106) | Mark price came from the sealed research epoch's last close, which was days old | **Fixed.** `app/research/pipeline.py` now marks at the latest live confirmed candle (`load_confirmed_candles(limit=1)` orders by `open_time DESC`). The 10-01 and 10-02 rollovers are clean (2.5 and 8.4 bps from bar close). | Excluded. All rollover exits (555) are excluded from signal research because the exit is forced, not strategy-driven. |
| `closed_at < opened_at` | 189 (subset of above) | `retire_at` was earlier than positions opened while the cycle was backtesting | **Fixed.** `lifecycle.py` now uses `closed_at = max(at, pos.opened_at)` and `retire_at = max(now, utcnow)`. | Excluded |
| Net P&L distortion | −$34.03 | Same | — | Excluded |
| `agent.realized_pnl` ≠ Σ trade net | 87 agents | All 87 hold a stale-rollover trade | Same fix | None (trade-level research) |
| Balance drift | 159 agents, total $1.39, max $0.037 (gens 1–3: 156; gen 6: 3) | 136 match **exactly** the entry fee of the agent's rollover position. This is the identity-map overwrite bug, fixed by `populate_existing` in `retire_generation`. The 3 gen-6 agents hold open positions: the entry fee is debited but not yet realized, which is expected. | Fixed | None |
| Trades without analytics row | 36 | Not determined | — | Excluded |

The excluded stale trades are 0.46% of all trades and do not change any conclusion.

## Clean Dataset & Effective Sample Size

| Item | Value |
|---|---|
| Candles | 12,027 confirmed SOL 1m, 2026-09-24 08:00 → 10-02 16:26 UTC |
| Trades | Signals 09-27 08:11 → 10-02 15:30; closes until 10-02 15:53 |
| Agents / generations | 2,725 trading (2,988 total) / 6 |
| Trades | 43,878 raw; minus 202 stale rollover, 353 clean rollover, 36 without analytics; **43,287 usable** |
| Directional agent signals (incl. risk-rejected) | 451,547 → **17,935 unique (bar, family, side)** |
| Traded unique signals | **6,500**, on 3,772 distinct signal bars |
| Trades per signal bar | mean 11.5, median 4, p90 30, max 290 |
| ICC of net bps within (bar, side) | **0.75** → design effect 7.1 → Kish effective n ≈ **6,058**, not 43,287 |
| Temporal clusters | 126 trading hours, 64 two-hour blocks |

**Implications:**

- Agents on the same bar take nearly the same trade, so 43k trades carry roughly the information of ~6k observations.
- Outcomes are also correlated in time, which leaves only ~64 independent blocks.
- All t-statistics here are clustered on 2-hour blocks. A segment with 50 signals cannot establish an edge of a few bps when the outcome standard deviation is 40–60 bps.

## Baseline

From `baseline_analysis.csv`. These are trade-level figures with real fills; all segments are listed in the CSV.

| Window (UTC) | Trades | WR | PF | Exp $ | Exp bps | Gross P&L | Fees | Slippage | Net P&L | Avg W / L | Payoff | BE WR | Max DD | Hold avg / median |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| All, 09-27 08:11 → 10-02 15:30 | 43,287 | 29.3% | 0.285 | −0.030 | −13.4 | −$461.4 | $842.2 | $466.3 | −$1,303.6 | 0.041 / −0.060 | 0.69 | 59.2% | $1,303.6 | 8.9 / 6.0 min |
| Last 72h (closed > 09-29 16:27) | 23,540 | 30.8% | 0.290 | −0.029 | −12.9 | −$228.0 | $459.8 | $256.9 | −$687.8 | 0.039 / −0.059 | 0.65 | 60.6% | $688.1 | 9.4 / 6.0 |
| Last 48h (> 09-30 16:27) | 15,043 | 31.2% | 0.316 | −0.028 | −12.1 | −$125.1 | $293.0 | $163.9 | −$418.1 | 0.041 / −0.059 | 0.70 | 58.9% | $418.1 | 9.8 / 6.0 |
| Last 24h (> 10-01 16:27) | 7,266 | 35.6% | 0.444 | −0.023 | −10.4 | −$31.4 | $135.1 | $75.0 | −$166.4 | 0.051 / −0.064 | 0.80 | 55.5% | $166.4 | 9.1 / 6.0 |
| Gen 6 (10-02 00:57 → 15:53) | 5,957 | 36.6% | 0.475 | −0.022 | −9.9 | −$20.6 | $110.0 | $60.8 | −$130.5 | 0.054 / −0.066 | 0.82 | 54.8% | $134.5 | 9.5 / 6.0 |

- Funding is ≈ $0 (−$0.06).
- Every family, regime and side is net-negative (see the CSV).
- Long: −14.3 bps. Short: −12.6 bps.

## Signal Horizon (1m → 60m)

From `horizon_analysis.csv`. Returns are signed forward returns from the next bar's open, in bps.

| Horizon | All signals mean (t) | Median | SD | Dir. acc. | Mean \|move\| | MFE / MAE | Net @ S1 13.5 | Net @ S6 8.0 | Net @ maker 3.0 |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|
| 1m | −0.02 (−0.27) | 0.0 | 8.9 | 47.2% | 6.2 | 5.2 / −5.0 | −13.5 | −8.0 | −3.0 |
| 3m | −0.02 (−0.14) | 0.0 | 15.6 | 48.0% | 11.2 | 10.1 / −9.9 | −13.5 | −8.0 | −3.0 |
| 5m | −0.10 (−0.43) | 0.0 | 20.2 | 48.0% | 14.6 | 13.5 / −13.3 | −13.6 | −8.1 | −3.1 |
| 10m | −0.28 (−0.65) | −0.8 | 27.6 | 48.0% | 20.1 | 19.5 / −19.5 | −13.8 | −8.3 | −3.3 |
| 15m | −0.23 (−0.39) | −0.8 | 32.8 | 48.3% | 24.2 | 24.0 / −24.2 | −13.7 | −8.2 | −3.2 |
| 30m | +0.90 (1.07) | 0.0 | 45.4 | 49.2% | 33.6 | 34.3 / −34.1 | −12.6 | −7.1 | −2.1 |
| 60m | +1.72 (1.73) | +1.6 | 66.0 | 50.4% | 49.7 | 49.9 / −48.6 | −11.8 | −6.3 | −1.3 |

- Traded signals look the same: +1.83 bps at 60m (t = 1.43), slightly negative at 3–30m.
- **Answer:** at no horizon does the signal produce enough directional movement to cover fees and slippage. The size of price moves grows with horizon, but the directional share of those moves stays ≈ 0.
- **Drift caveat:** SOL fell 349 bps (124.27 → 119.93) over the trading window. Short signals therefore received about +2.5 bps per 60 minutes from drift alone. Short-tilted segments below should be read with that in mind.

## Cost Analysis

From `cost_analysis.csv`. Scenarios are applied to the mid-price outcome of the actual trades.

| Scenario | Exp bps (t) | PF | WR | Net $ | Max DD $ |
|---|--:|--:|--:|--:|--:|
| S1 current (actual fills: fees 8.67 + slip 4.81) | −13.40 (−19.4) | 0.286 | 29.3% | −1,303.6 | 1,303.6 |
| S2 lower slippage (fees + 2 bp) | −10.59 | 0.353 | 31.0% | −1,031.2 | 1,031.2 |
| S3 maker both sides (3 bp, no slippage) | −2.92 (−4.5) | 0.737 | 36.4% | −286.0 | 293.0 |
| S4 zero slippage (taker fees) | −8.59 | 0.427 | 32.8% | −837.3 | 837.3 |
| S5 zero fee (slippage only) | −4.72 | 0.629 | 35.9% | −461.4 | 461.4 |
| S6 plausible maker (maker in, taker out + 2 bp) | −7.92 | 0.448 | 33.4% | −770.9 | 770.9 |
| Frictionless | +0.08 (0.13) | 1.009 | 38.0% | +4.9 | 68.0 |

- **The strategy is not a useful signal destroyed by costs. It has ≈ 0 gross edge, and costs are the entire loss.**
- Even fully maker execution with zero slippage loses 2.9 bps per trade with t = −4.5. That scenario is optimistic and also ignores adverse selection.

## Minimum-Move Analysis

From `min_move_frequency_analysis.csv`, pooled across the 3 OOS windows. The minimum-move filter keeps a signal only when ATR × √h is at least the threshold.

| Universe, horizon | No filter | ≥ 30 bps | ≥ 50 bps | Retained at 50 |
|---|--:|--:|--:|--:|
| Traded, 10m | −13.8 | −14.5 | −13.1 | 7% |
| Traded, 30m | −12.0 | −11.9 | −14.0 | 35% |
| Traded, 60m | −9.1 | −9.1 | −8.5 | 76% |
| All signals, 10m | −12.8 | −11.8 | −8.0 | 11% |

Filtering for high-movement environments raises the size of moves, not their direction. No threshold made net expectancy positive. Thresholds of 5–20 bps are non-binding at 30m and 60m.

## Order Flow

From `order_flow_analysis.csv` and `order_flow_prespecified_check.csv`.

- **What it is.** `flow_imbalance_p` = Σ sign(close − open) × volume / Σ volume over p bars. It is a bar-based proxy; no tape, book or spread data exists. I evaluated it on every bar, independent of the agents.
- **Continuation strength (p = 10, mean forward 30m in bps).**

  | Bucket | Fwd 30m | t |
  |---|--:|--:|
  | Strong negative | +3.0 | 1.07 |
  | Weak negative | +6.0 | 1.48 |
  | Neutral | −0.9 | — |
  | Weak positive | +0.2 | — |
  | Strong positive | +2.9 | 0.89 |

  No monotonic relationship, and no |t| > 2.
- **Conditions tested.**
  - Persistence (3 bars): +2.6 (t = 1.43).
  - Acceleration: +2.3.
  - Flow **against** 10m momentum: +3.8 at 30m and +6.9 at 60m (t = 1.84 / 2.14), stable in 4/4 quarters. This is still far below the 13.5 bps cost.
  - Volume spike: +3.6.
  - High volatility: +0.9.
  - By regime: TREND_DOWN +7.0 at 30m and +14.8 at 60m (t = 2.0), but only 209 bars and helped by drift.
- **Order-flow strategy, fixed hold, untuned, per OOS window at S1:**

  | Hold | F1 | F2 | F3 |
  |---|--:|--:|--:|
  | 30m | −4.1 | −8.2 | +8.2 |
  | 60m | −6.0 | −5.5 | +11.8 (t = 1.1, n = 67) |

  Using all order-flow signals, including risk-rejected ones, is worse: −6.5 / −11.1 / +7.8 at 60m.
- **Verdict:** at best a weak continuation tendency of 2–7 bps. It is unstable, below costs, and its only positive window is the most recent day, which includes drift. No simple deterministic edge.
- The top-confidence order-flow figures in the marginal table (+38 to +57 bps at top 10%) use **in-window quantiles on 17 signals**. They are descriptive only and are **not** a tradable result.

## Strategy Analysis

From `strategy_analysis.csv`.

| Family | Signals (all / traded) | Trades | Mid bps (t) | Net bps | PF | Quarters mid > 0 | Quarters net > 0 |
|---|---|--:|--:|--:|--:|--:|--:|
| order_flow | 512 / 271 | 2,105 | +3.78 (0.95) | −8.9 | 0.56 | 3/4 | 0/4 |
| vwap | 5,475 / 1,802 | 11,967 | +1.02 (0.65) | −12.7 | 0.35 | 3/4 | 0/4 |
| mean_reversion | 2,207 / 1,233 | 11,975 | +0.99 (0.94) | −12.9 | 0.24 | 3/4 | 0/4 |
| scalping | 3,095 / 1,260 | 5,747 | +0.12 (0.40) | −13.0 | 0.14 | 3/4 | 0/4 |
| market_structure | 1,375 / 479 | 1,901 | −1.62 | −15.0 | 0.28 | 2/4 | 0/4 |
| momentum | 725 / 399 | 5,335 | −1.81 | −14.8 | 0.29 | 2/4 | 0/4 |
| hybrid | 4,143 / 844 | 2,100 | −3.61 (−3.2) | −16.9 | 0.24 | 1/4 | 0/4 |
| breakout | 161 / 133 | 1,721 | −4.05 | −17.2 | 0.23 | 2/4 | 0/4 |
| trend_following | 235 / 76 | 427 | −4.30 | −17.5 | 0.39 | 1/4 | 1/4 |

Excluded: volatility (9 trades).

- No family has a significant positive mid-price edge.
- No family is net-positive in more than 1 of 4 quarters.
- Hybrid is significantly negative even at mid prices.

## Regime Analysis

From `regime_analysis.csv`.

- **Single regimes.** No regime has |t| > 2 at 30m. TREND_UP traded signals are negative at 60m (−9.9, t = −2.5).
- **Strategy × regime × side** (traded, ≥ 30 bars):
  - 40 combos.
  - 4 combos have forward 30m above cost overall.
  - **0 combos are above cost in ≥ 3 of 4 quarters.**
  - 0 combos have t > 2.5.
- **All signals:** 49 combos, of which 1 is above cost in ≥ 3 quarters: trend_following / TREND_DOWN / SHORT, 96 signals, +14.3 bps at 30m (t = 4.1). It is short-side in a falling market, comes from a 96-signal family, and is 1 of 49 tests, so it is a multiple-comparison artifact until proven otherwise.
- The walk-forward search could select combos like this and did not find any that held up on OOS.

## Direction

From `direction_analysis.csv`.

- Long and short are both ≈ 0 at every horizon:
  - Long: +0.8 at 30m, +0.4 at 60m.
  - Short: +1.0 at 30m, +3.0 at 60m. The 60m short figure is about what drift alone would give (+2.5).
- Conditional asymmetries (for example HIGH_VOLATILITY SHORT +10 at 30m, RANGE LONG +4.9 at 30m) flip sign across quarters.
- No persistent directional advantage.

## Entry Quality

From `entry_analysis.csv`. Traded signals, 30-minute window, cost 13.5 bps.

| Class | Actual direction | Opposite-direction benchmark |
|---|--:|--:|
| A bad direction (MFE < 5 bps) | 13.8% | 12.4% |
| B correct but insufficient (5 ≤ MFE < cost) | 17.7% | 15.4% |
| C reached cost then reversed | 35.1% | 36.8% |
| G reached cost and held | 33.4% | 35.3% |

Supporting measurements:

- First bar adverse: 49.1% (benchmark 49.7%).
- MFE − |MAE| ≈ 0 at every horizon.
- Median time to MFE and to MAE within 60m: 28 and 26 bars.
- **D (execution):** 12.4% of signals are positive at mid but net-negative. Mean mid −0.49 bps vs net −13.90 bps.

**Diagnosis.** The problem is not one of A, B or C specifically. The signal has **no information about direction**: the outcome mix is the same as entering the opposite way. Execution (D) turns that zero into −13.5 bps.

## Exit Analysis

From `exit_analysis.csv` and `exit_walkforward.csv`. Offline simulation on 6,498 traded signals:

- SL/TP sized as multiples of ATR, maximum hold 60m.
- Stop assumed to fill first when both levels are hit in the same bar.
- Costs: stop 15 bps, take-profit 8 bps, time exit 13 bps.

| Exit | Net bps | PF | vs. flipped direction |
|---|--:|--:|--:|
| Existing exits (real fills) | −13.9 | — | — |
| Fixed 60m | −11.2 | 0.63 | +3.7 |
| SL 4×ATR / TP 1×ATR | −11.4 | 0.14 | −1.3 |
| SL 2×ATR / TP 4×ATR | −12.7 | 0.44 | −1.8 |
| Trailing variants | −13.4 to −14.7 | — | — |

- No exit is positive.
- Frictionless results are between −1.7 and +1.8 bps for every exit.
- **Validation-chosen exits on OOS:** −11.4 / −10.3 / −13.4 bps, versus the existing −14.3 / −13.8 / −11.8.
- **As expected, exit design cannot create an edge the entries don't have.**

## Statistical Validation

From `walkforward_selection.csv`.

- **Folds (UTC, by signal bar, 1h embargo):**

  | Fold | Validation | OOS |
  |---|---|---|
  | F1 | 09-28 20:00 → 09-29 19:00 | 09-29 20:00 → 09-30 19:00 |
  | F2 | 09-29 20:00 → 09-30 19:00 | 09-30 20:00 → 10-01 19:00 |
  | F3 | 09-30 20:00 → 10-01 19:00 | 10-01 20:00 → 10-02 16:30 |

  Training data always starts 09-27 08:00.
- **Selection rule (fixed in advance):** maximize mean validation net at the scenario's cost, requiring ≥ 30 signals and ≥ 20 distinct bars.

| Fold | Selected at S1 | Validation | OOS n | OOS exp | OOS PF | OOS t |
|---|---|--:|--:|--:|--:|--:|
| F1 | order_flow traded, 60m, ATR√h ≥ 50, top 75% conf | +15.2 | 36 | +3.2 | 1.09 | 0.23 |
| F2 | bar order-flow p5 \|fi\| > 0.45, vr > 1.4, 60m, top 25% | +14.4 | 23 | −2.9 | 0.85 | −0.17 |
| F3 | vwap traded, 60m, top 50% conf | +15.9 | 152 | **−30.0** | 0.47 | −1.69 |

Success criteria:

| Requirement | Result |
|---|---|
| R1 positive net after realistic cost | **FAIL** (1/3 windows; pooled −21.4 bps) |
| R2 PF > 1 | **FAIL** |
| R3 positive across OOS windows | **FAIL** |
| R4 not driven by a single period | **FAIL** (quarters positive: 1, 1, 2) |
| R5 adequate size | **FAIL** (OOS bars 23–150) |
| R6 no leakage | Pass (decision-time features only; entry at next open) |
| R7 survives slippage | **FAIL** |

Under S6 (plausible maker), the selected rules were positive in 2 of 3 windows but pooled −15.9 bps.

**Every validation edge of about +15 bps shrank to roughly 0 or below on OOS. That is the signature of selecting on noise.**

## Recommended Architecture

None is supported by OOS evidence. I'm not recommending any `Signal → filter → … → Trade` pipeline, because no component (regime filter, minimum move, order-flow confirmation, confidence, cooldown, horizon or exit) improved realistic-cost OOS expectancy in a stable way.

## Production Recommendation

**A. KEEP CURRENT SYSTEM**, meaning do not deploy any new strategy, filter, exit or model from this research. Note that the current system itself loses about 13 bps per trade.

## The Most Important Question

> If we change the horizon, reduce turnover, account for costs and trade only high-movement signals, is there evidence this system can become profitable?

**No.**

**What prevents profitability.** The strategy families as built produce directional calls with ≈ 0 information:

- Frictionless +0.08 bps per trade; best broad horizon +1.7 bps at 60m (t = 1.7).
- Direction choices are statistically equal to their mirror image.

**The missing edge, quantified.** A configuration needs mean signed forward return above its round-trip cost.

| Cost scenario | Required | Observed best broad edge | Gap |
|---|---|---|---|
| Realistic (S1) | > 13.5 bps | ≈ +1–2 bps | **≈ 12 bps per trade** |
| Plausible maker execution | > 8 bps | ≈ +1–2 bps | ≈ 6 bps |
| Fully maker execution | > 3 bps | ≈ +1–2 bps | ≈ 1–2 bps, not statistically established |

The gap could only be closed by a source of directional information these candle-derived signals lack, *and* by cheaper execution.

**What would be needed:**

1. **New information, not new filters on the same candles.**
   - Real order-flow data: trade tape with aggressor side, order-book imbalance, spread and depth. Hyperliquid's L2 book and trades feed provide this.
   - Funding and open-interest changes, liquidation flow, and cross-venue or cross-asset leads (for example BTC → SOL).
   - Today `order_flow` is a candle-colour proxy.
2. **More data and more independent observations.** 5.3 days ≈ 64 two-hour blocks. Detecting a 3–5 bps edge with outcome SD ≈ 45 bps at 30m needs roughly 3,000+ independent signals spanning several weeks and regimes (a down-drift week alone is not enough).
3. **An execution model that can be validated.** If maker fills are assumed, the shadow layer must log queue position and fill rate. Without that, maker scenarios are only an upper bound.
4. **Fewer, independent decisions.** Hundreds of agents on the same bar multiply cost without adding information (ICC 0.75). Any future candidate should be judged on independent signals, not agent-trades.

## Reproduction

Run on a machine with the backup restored to 127.0.0.1:55432, using a venv with pandas 2.2.3, numpy 2.1.1, scikit-learn 1.7.2, psycopg2-binary, pyarrow and scipy.

1. Run `../entry_quality_2026-10-02/extract.py` and `extract_decisions.py`. These produce the parquet extracts, using read-only SQL inside the scripts.
2. Then run `p2_main.py`, `p2_wf.py` and `p2_orderflow_check.py`.

Settings:

- Data directory: `P2_DATA` (defaults to `../entry_quality_2026-10-02/data`).
- No randomness is used; selection is deterministic.
- Fold boundaries, costs and grids are constants in `p2lib.py` and `p2_wf.py`.

Console outputs are in `p2_main_out.txt` and `p2_wf_out.txt`.
