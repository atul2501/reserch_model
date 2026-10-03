# Forensic Audit: Why the Trading System Cannot Make Money

| Item | Detail |
|---|---|
| Backup | `trading_lab_20261002_162728.dump` |
| Restored to | Isolated Postgres at 127.0.0.1:55432, DB `trading_lab_research_20261002` |
| Scope | Read-only. No production code, database, EC2, configuration or V1 was changed. |
| Exchange data | Public Hyperliquid candle data was fetched for two cross-checks: SOL candle verification and the BTC lead-lag test. |

**Deliverables in this folder**

| File | Content |
|---|---|
| `trade_trace_examples.csv` | 30 end-to-end traces |
| `feature_leakage_audit.csv` | 28 features / feature groups |
| `pnl_reconciliation.csv` | All 43,878 trades |
| `execution_audit.csv` | Execution checks |
| `strategy_signal_audit.csv` | Per-family signal behaviour |
| `prompt_audit.md` | LLM prompt and role audit |
| `loss_waterfall.csv` | Where expectancy disappears |
| `forensic.py`, `independent_backtest.py`, `btc_leadlag.py` | Scripts |
| `*_out.txt` | Raw outputs |

---

## Executive Summary

**The system loses money because it trades about 8,000 times a day on signals that contain no information about where SOL goes next, and every trade pays about 13.5 bps in fees and slippage.**

- **Before costs the average trade makes +0.08 bps; after costs it loses 13.4 bps.**
- **The losses are real, not an accounting artifact.** I recomputed every trade independently: gross, fees, funding and net match the database on all 43,878 trades. A separate backtest written from scratch reproduces the Phase 2 numbers to 0.03 bps.
- **There is no look-ahead.** I replayed features and signals with production code using only data available at each decision; they match the stored decisions 100% (30 traces plus 400 random decisions).
- **The signal design is the problem.**
  - **Trend-type strategies are late.** They react to moves that have already happened: 24–113 bps in the prior 10–30 minutes. After entry the price goes nowhere.
  - **Fade-type strategies get no reversion.** They enter against moves and the price doesn't come back.
  - **Entries look random.** Their outcome mix is statistically identical to entering the opposite way.
- **The LLM council adds no information, but it also isn't the cause.**
  - Its directional calls are right 48% of the time (t ≈ 0.3).
  - It influences only 17% of trades.
  - Removing it would leave expectancy at about −13 bps.
- **The bugs I found are real but not why the system loses.**
  - The stale-price rollover bug and fee-ledger bug are already fixed in code.
  - The cross-agent indicator contamination affects audit fields only.
  - The timestamp label bug and two optimistic fill assumptions are each worth under 0.5 bps.

## Most Likely Root Cause (ranked by evidence)

| Rank | Category | Verdict | Evidence |
|---|---|---|---|
| 1 | **E — Strategy problem** | **Primary** | Mid-price edge is +0.08 bps per trade; fixed-hold edge is −0.6 to +1.8 bps (all \|t\| < 1.8). Outcome mix equals the opposite-direction benchmark. 9 of 10 families show no follow-through. Same strategy across generations: Spearman −0.03, so there is no persistent skill. |
| 2 | **F — Information problem** | **Primary (why E happens)** | Every input (DNA rules, regime, LLM) is a function of the same 1-minute public OHLCV. BTC lead-lag holds a little information, but only about 1 bps at 1-minute resolution. There is no book, tape, liquidation, cross-venue or sub-minute data. |
| 3 | **G — Cost problem** | **Amplifier, not a hidden edge** | Costs are 13.47 bps per trade, equal to 86% of the median stop distance and about the median 10-minute move. Even zero-cost trading would make only +0.08 bps. |
| 4 | **H — Architecture problem** | **Contributing** | About 500 agents fire the same signals (ICC 0.75); `vwap`/`hybrid` signal on 54–65% of all bars. Evolution selects on noise. Stops of ~1–3× the 1-minute ATR are about the size of the cost. |
| 5 | **D — Target/prediction problem** | **Contributing (ML layer only)** | The V1 target (`net_pnl > 0`) mixes exit mechanics with direction and rewards win rate. Evolution fitness is in-sample composite fitness over 1-day generations. Neither target is "expected move > cost". |
| 6 | **C — Execution-model bug** | **Minor, slightly optimistic** | TP fills when a bar merely touches the level (17% of TP exits), worth at most 0.41 bps per trade. Entry is priced at an open 3–17 s before the decision. Neither explains the losses. |
| 7 | **A — Code bug** | **Minor** | See below. No bug changes the sign or rough size of expectancy. |
| 8 | **B — Data bug** | **Minor** | Candles match the exchange: opens 100%, closes 99%. 1% of closes are frozen about 1 bp early. |

## Code Bugs (confirmed)

**1. Stale-price generation rollover.** Already fixed in code; still present in this backup.
- 202 trades from the 09-28, 09-29 and 09-30 rollovers settled at 123.36 against a market of about 118.8; 189 of them have `closed_at < opened_at`. Net distortion: −$34.03.
- Fix in `research/pipeline.py:393-396` (marks at the latest live confirmed candle) and `agents/lifecycle.py:225` (`closed_at = max(at, opened_at)`).
- The 10-01 and 10-02 rollovers are clean.

**2. Rollover balance overwrite.** Already fixed.
- 136 of the 159 balance drifts equal exactly the entry fee of the agent's rollover position.
- Cause: an identity-map overwrite, fixed with `populate_existing` in `retire_generation`.
- The other 3 drifts in generation 6 are open positions, which is the correct accounting.

**3. Cross-agent indicator contamination.** Open; confirmed by replay.
- `strategies/families.py::_find(f, prefix)` returns the first sorted key matching `flow_imbalance_`, `roc_`, `zscore_`, `donchian_*_`. It searches a feature dict computed for the whole population (`decision_loop.compute_population_features`).
- Example: an agent declaring `flow_imbalance_20` had its setup strength and confidence computed from `flow_imbalance_15` or `flow_imbalance_10`. Production confidence is reproduced only with the population dict (2 of 2 cases).
- Impact:
  - `setup_strength` and `signal_confidence` are wrong for multi-period families. These are audit fields only, though Phase 1 ML used them as features.
  - Direction is affected only for `direction_mode="auto"` agents: 52 agents, all in the volatility family, whose direction function doesn't use `_find`. **Effectively no P&L impact.**
- Fix: resolve the agent's own declared keys instead of a prefix search.

**4. Exit timestamp label.**
- Signal exits (`exit_rules`, `signal_reversal`; 16,886 trades, 100% of them) fill at the bar **open** but are stamped `closed_at` = bar **close** (+59.999 s). Code: `_close_position` uses `cc.close_dt`.
- `holding_seconds` is overstated by about 1 minute, and post-exit analytics windows include one extra bar.
- No P&L impact.

**5. Trade rows without analytics.** 36 trades lack a `trade_analytics` row. Root cause not determined.

**Found correct:**
- P&L engine: net = gross − fees − funding; slippage is informational only.
- Fee rates; funding sign.
- Next-open fill timing; stop gap handling.
- Pending-order expiry; candle finality gate.
- Council fail-closed behaviour; idempotency keys.

## Data Problems

- **Candles agree with Hyperliquid** on 5,099 overlapping bars (09-29 → 10-02):
  - opens identical (100%);
  - highs, lows and closes identical on 98.4–99.9% of bars;
  - 53 closes (1%) differ by a median 0.85 bps (max 9 bps), and volumes differ on 1.5% of bars.
- **Cause of the differences:** `CANDLE_FINALITY_GRACE_MS=1500` sometimes freezes a bar before its final trade, and later revisions are deliberately ignored. This is economically negligible but is a real data-fidelity gap.
- **No other data defects:** no duplicates, gaps, OHLC violations, timezone errors or future timestamps (Phase 1 audit, re-checked).
- **Funding/OI** are recorded on 7,451 of 12,028 bars, as an intrabar snapshot. They are not used by any strategy.

## Prompt Problems

See `prompt_audit.md`.

- **The LLM is a size and veto modifier,** not the signal source, and it runs on only every 5th candle.
- **Its prompt is missing the key facts:** fees, horizon, minimum profitable move, position, price history and unit definitions.
- **It contains nothing the strategies don't already have.**
- **Result:**
  - Directional accuracy is 48%.
  - The vetoes removed slightly *profitable* signals (+4.6 bps, t = 0.9).
  - Aligned vs opposed trades differ by about 1–3 bps, which is noise.
- **Parsing, defaults, retries and quorum handling are correct.** 99.97% of responses were valid; no silent default direction.

## Target Problems

- **Strategy layer.** There is no learned target. DNA rules are hand-built indicator conditions mutated by evolution.
- **Evolution target.** In-sample composite fitness over about 1-day generations.
  - Fitness correlates with the agent's own realized expectancy (Spearman 0.58), as expected in-sample.
  - Skill does not persist: the same strategy version across consecutive generations shows Spearman −0.03 (42 pairs).
  - **Selection is selecting noise.** Generation mean net was −16.3 / −14.9 / −11.4 / −15.0 / −13.3 / −9.8 bps, with no learning trend beyond regime drift.
- **V1 ML target.** `net_pnl > 0`.
  - It mixes direction with TP/SL geometry and rewards win rate.
  - Phase 1 showed higher V1 probability came with higher win rate but **lower** expectancy.
- **The economically correct target was never used anywhere:** E[signed move over the intended horizon] − round-trip cost > margin.

## Strategy Problems

From `strategy_signal_audit.csv`.

| Family | Bars with a signal | Prior 10m move (signal direction) | Prior 30m move | Next 30m | Character |
|---|--:|--:|--:|--:|---|
| vwap | 65% | −10.2 | −26.4 | +0.4 | Fades the move; no reversion |
| hybrid | 54% | +24.1 | +26.9 | +1.8 | Chases the move; no follow-through |
| scalping | 40% | +15.9 | +16.3 | +0.1 | Chases the move; no follow-through |
| mean_reversion | 29% | −25.3 | −29.1 | −1.0 | Fades the move; no reversion |
| market_structure | 18% | +3.1 | +30.4 | +2.3 | Chases the move; no follow-through |
| momentum | 9% | +31.3 | +73.5 | +1.0 | Chases the move; no follow-through |
| order_flow | 6% | +30.0 | +44.8 | +5.7 (t 1.7) | Chases the move; no follow-through |
| trend_following | 3% | +35.1 | +112.9 | +2.2 | Chases the move; no follow-through |
| breakout | 2% | +38.7 | +51.4 | +5.8 | Chases the move; no follow-through |

- **"Too late" is confirmed, but the cause is indicator lag, not execution latency.**
  - Execution latency costs nothing: signal close → fill-bar open averages **0.0013 bps** (t = −0.03).
  - The lateness is in *what* the signal detects. EMA/MACD/ROC/RSI/flow conditions become true only after a 25–110 bps move has printed, and on 1-minute SOL that move has no measurable continuation.
- **Signals are states, not events.**
  - vwap, hybrid and trend signals repeat on the previous bar 85–87% of the time, and their net direction has lag-1 autocorrelation of 0.83–0.85.
  - So hundreds of agents re-enter the same idea bar after bar.
- **Entries are indistinguishable from random direction** (Phase 2):
  - The class mix matches the opposite-direction benchmark within 2 points.
  - The first bar is adverse 49.1% of the time vs 49.7% for the opposite direction.

## Execution Problems

From `execution_audit.csv`.

- **Entry.**
  - Reference price = the open of the bar after the signal (100% of trades), plus 2.00 bps modelled slippage (independent recompute matches to 0.000 bps mean).
  - **Optimism:** the fill uses an open price **3.1 s (p50), 11.2 s (p90) and 17.1 s (p99) earlier than the decision was written.** That's longer on council candles.
  - The bias is not measurable with 1-minute data, and since the entries have no directional edge its expected value is about 0. A live system would fill at a later, unknown price.
- **Take-profit.**
  - Fills exactly at the level (99.85%) with zero slippage and the maker fee (6.0 bps round trip vs 9.0).
  - 808 TP exits (17%) only *touched* the level (< 1 bp through), so a live resting order might not have filled.
  - Upper bound of the optimism: **0.41 bps per average trade**.
- **Stop.**
  - Fills at the level plus 4.00 bps (2× slippage model), or at the gapped open (2.4% of stops). Conservative and correct.
  - When a bar touches both stop and TP, the stop is assumed to fill first (conservative).
- **Slippage is modelled, not observed.**
  - A flat 2 bps + 0.5 bps per $10k (×2 on stops).
  - SOL perp half-spread on Hyperliquid is typically below 1 bp, so modelled slippage may be **pessimistic** by about 1–3 bps per trade for $20 orders.
  - Even with zero slippage the system loses −8.6 bps (Phase 2).

## P&L Problems

From `pnl_reconciliation.csv`.

- **Independent recompute matches all 43,878 trades exactly** (|diff| = 0 at 1e-9):
  - gross = (exit − entry) × qty × direction;
  - fees = entry notional × 4.5 bps + exit notional × (4.5 or 1.5 bps for TP);
  - net = gross − fees − funding.
- **Funding** equals the sum of `funding_payments` (0 mismatches). Total funding ≈ $0.
- **Reported cost is correct:** fees 8.67 bps + slippage 4.81 bps = **13.47 bps**.
- **Agent ledgers** reconcile except for the known rollover rows (bugs 1 and 2 above).

## Trade Traces

`trade_trace_examples.csv` holds 30 trades:

- every exit type (stop, TP, exit_rules, signal_reversal, trailing, clean rollover, stale rollover);
- both sides, all 10 families, all 6 generations;
- holds from 0 to 16,319 s; winners and losers.

| Check | Pass rate |
|---|--:|
| Production feature replay from candles ≤ signal bar equals stored features (close, RSI, ATR, regime) | 30/30 |
| Order-intent ATR equals replay ATR | 30/30 |
| Signal direction replay equals DB | 30/30 (and 400/400 random decisions) |
| Confidence replay | 28/30 (2 order_flow cases explained by bug 3) |
| Order requested price equals signal-bar close | 30/30 |
| Independent stop equals DB | 30/30 |
| Independent TP equals DB | 30/30 |
| Independent net P&L equals DB | 30/30 |

- **Protective exits:** for every stop and TP trace, the independent bar-path replay picks the same exit bar and type.
- **Decision → fill lag:** 2.5–19.9 s.

**No discrepancy was found between what the system thinks happened and what actually happened**, apart from the documented bugs.

## Loss Waterfall

Per average clean, non-rollover trade, in bps of entry notional (`loss_waterfall.csv`).

| Component | bps | t |
|---|--:|--:|
| Signal latency (signal close → fill-bar open) | −0.00 | −0.03 |
| Raw directional move over the actual hold (mid) | −0.57 | −0.75 |
| Exit logic (exit reference vs exit-bar close) | +0.66 | +2.91 |
| **= Gross edge at reference prices** | **+0.08** | |
| Entry slippage | −2.00 | |
| Entry fee | −4.50 | |
| Exit slippage | −2.79 | |
| Exit fee | −4.18 | |
| Funding | +0.00 | |
| **= Final expectancy** | **−13.38** | (DB: −13.38) |
| Memo: fixed 10m hold, exit-independent edge | +1.25 | +1.25 |

**Where the money disappears:** 100% of the loss is execution cost charged on an edge of about 0.

- Fees: 8.68 bps (65%).
- Slippage: 4.79 bps (35%).
- The exit logic's small +0.66 bps comes from limit-priced TPs and stop-level fills, and it is partly the TP optimism noted above.

## Information Gap

**What the system has:** SOL 1-minute OHLCV, about 40 indicators derived from it, a rule-based regime label, an LLM restating those indicators, and an intrabar funding/OI snapshot. None of this is private, fast, or unpriced.

**What it lacks:**

| Missing information | Status |
|---|---|
| Order-book state (L2 imbalance, depth, microprice, spread) | Available from the Hyperliquid WS `l2Book`; never collected |
| Trade tape with aggressor side (true order flow, trade-size distribution) | `trades` feed; never collected. Today's "order_flow" is a candle-colour proxy. |
| Sub-minute timing | All decisions are on 1-minute closes and fill a bar later |
| Cross-asset leads | BTC test: lead-lag exists (BTC residual vs SOL next 1m, corr +0.05, about 8× SOL's own autocorrelation) but is worth only about 0.7–0.9 bps at 1-minute resolution (t ≈ 1.4), because nearly all co-movement happens within the same minute (same-bar corr 0.81) |
| Liquidations, OI/funding *changes* at event time, cross-venue basis | Not collected |
| Execution quality data (real fill rate of passive orders) | Required before assuming maker costs |

## Recommended Architecture

Only for what the audit supports. Do not add components that have no evidence behind them.

1. **Fix the two open low-impact bugs** (3 and 4) and the TP touch-fill assumption: require penetration of at least 1 tick, or simulate queue position. This is for honest accounting, not profit.
2. **Separate "does information exist?" from "can we trade it?"** Every candidate signal should first pass an offline **information test**: signed forward return at its intended horizon, clustered t-stat, on data it was not designed on, compared against the round-trip cost of the intended execution style. **Nothing currently in the system passes.**
3. **Collapse the population to independent signals.** Judge evolution and fitness on de-duplicated signals and on out-of-sample windows, not on 500 correlated agents' in-sample P&L.
4. **Keep the LLM out of the signal path** unless it receives information the rules don't have and its calls are tested the same way. Today it measures at 48% accuracy.

## Next Experiment (one)

**A no-trade microstructure information study on Hyperliquid SOL.**

1. Record the L2 book (top 10 levels) and the trade tape with aggressor side for 2–4 weeks.
2. Run this in the existing shadow infrastructure. It places no orders.
3. Pre-register a handful of standard features: top-of-book and depth imbalance, microprice − mid, signed trade-flow imbalance over 1–60 s, and BTC/ETH 1-second residual moves.
4. Measure their predictive power for SOL mid-price over 1 s to 5 min with clustered statistics, against the cost of **passive** execution (also logged: would a resting order at the touch have filled?).

**Success criterion:** a pre-registered feature with out-of-sample mean signed move clearly above passive cost (more than about 3–5 bps) at t > 3, stable across weeks.

**If no feature passes**, stop investing in short-horizon SOL directional trading on this stack.

## Answers

| # | Question | Answer |
|---|---|---|
| Q1 | Is the loss caused primarily by a bug? | **No.** Every trade reconciles; an independent backtest reproduces the loss; no look-ahead. The bugs found move expectancy by under 0.5 bps or are already fixed. |
| Q2 | Primarily by the strategy? | **Yes.** The signals carry no directional information (mid edge +0.08 bps); they react to moves already finished, and the strategies trade continuously. |
| Q3 | Primarily by the prompt/LLM? | **No.** The LLM adds nothing (48% accuracy) but touches only 17% of trades and doesn't make them worse in a measurable way. |
| Q4 | Is the target definition wrong? | **Yes, but it's secondary.** Neither the evolution fitness nor the V1 target expresses "expected move > cost", and selection picks noise (Spearman −0.03 across generations). Fixing the target cannot create an edge that the inputs lack. |
| Q5 | Is execution cost the primary issue? | **It is the immediate arithmetic of the loss** (100% of −13.4 bps), **not the root cause.** With zero cost the system makes about 0 (+0.08 bps). |
| Q6 | Any measurable predictive edge before costs? | **No.** All horizons from 1 to 60 minutes have \|t\| < 1.8. Directional accuracy is 47–50%. |
| Q7 | If yes, how many bps? | Not significant. The point estimate is +0.08 bps per trade (realized), and +1.25 bps on a fixed 10-minute hold (t 1.25), against 13.5 bps cost. |
| Q8 | What information is missing? | Faster, non-OHLCV information: order book (imbalance, depth, microprice), aggressor-side trade flow, sub-minute cross-asset leads (BTC), liquidation and OI/funding events, plus measured passive-fill rates. Candle-derived indicators on 1-minute SOL are already priced in. |
| Q9 | Single biggest change required? | **Replace the signal source.** Build signals from information that can lead price (microstructure and cross-asset at sub-minute resolution), validated by an information test against the cost of the execution style actually used, before any agent, LLM or ML layer is put on top. |
| Q10 | Continue improving this architecture, or redesign signal generation? | **Redesign signal generation.** The plumbing is sound and can be kept: data ingestion, finality gates, accounting, risk, paper execution, audit trail. The signal layer cannot be tuned into profitability: indicator-rule DNA plus evolution plus an LLM restating indicators. Phases 1–2 and this audit tried ML, horizons, filters, exits, costs and selection, and found nothing to tune. |
