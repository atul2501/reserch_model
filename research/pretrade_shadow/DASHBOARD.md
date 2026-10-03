# Dashboards: `/pretrade-shadow` and `/research-lab`

**Access.** Both pages are viewer-authenticated, like every existing page: the browser prompts once for an API key with viewer role or higher. They are read-only. Every pre-trade-shadow number is **hypothetical**; shadow never placed an order.

**Data sources.**

| Page | API | Data |
|---|---|---|
| `/pretrade-shadow` | `GET /api/pretrade-shadow/summary?horizon=10&hour_group=1` | Shadow JSONL (`PRETRADE_SHADOW_DIR`), confirmed candles, the paper path's own orders and trades (read-only), worker cycles |
| `/pretrade-shadow` (raw rows) | `GET /api/pretrade-shadow/decisions.csv` | One row per shadow candidate |
| `/research-lab` | `GET /api/research-lab/summary` | Experiment registry (`research/edge_registry/experiments.jsonl`), data coverage, the proposer |

The dashboard API and `python -m scripts.export_pretrade_shadow` call the same `app.pretrade.assemble.assemble()`, so they cannot disagree.

---

## `/pretrade-shadow`

The page has one question: **can the pre-trade path find trades with positive expectancy after realistic costs?**

| Section | Shows | Source / rule |
|---|---|---|
| **A · Live shadow status** | Trading and pre-trade mode; shadow RUNNING/STALE/NO DATA; start; duration; last decision; last market time; last shadow cycle; **missed shadow cycles** | RUNNING = a shadow cycle within the last 3 min. "Missed" = worker cycles COMPLETED after shadow start with no shadow record, which is the shadow-error count visible across processes. |
| **B · Opportunities** | Candidates, would trade/reject, pass/reject %, rejection categories: minimum_notional, duplicate_position, cooldown, position_open, pending_order, stale, price_drift, spread, risk, regime, conflict, other | Gate reasons and risk reasons, mapped in `app/pretrade/report.categorize`. A candidate can carry several reasons. |
| **C · Signal edge** (most important) | For ALL, GATE-PASS, GATE-REJECTED, LONG and SHORT at 1/5/10/30/60 min: n, independent bars, gross mean/median, **net win rate, net PF, NET expectancy**, clustered t, block-bootstrap 95% CI, warnings | The return is measured from the real book mid at the shadow execution point to the confirmed bar close at the horizon. It is NULL until that bar exists. The cost is **measured** from paper fills. |
| **D · Gross vs net** | Gross move − fees − slippage = **net**, plus the measured spread | Fees and slippage come from paper trades (`cost_source`). Spread is shown separately and not added a second time. |
| **E · MFE/MAE** | At 1/5/10/30/60 min, for ALL/LONG/SHORT, by strategy and by regime | High/low of bars K+1..K+h, used as a *measurement*, never as a fill. MFE far above \|MAE\| with near-zero return means good entries and bad exits; MFE ≈ \|MAE\| means the entry has no edge. |
| **F · Strategy** | Signals, gate-pass %, win rate, gross/net expectancy, PF, MFE/MAE, paper hold avg/median, paper fee/slippage | Existing strategy families only. |
| **G · Regime** | The same, by the existing rule-based regime | |
| **H · Time of day** | By UTC hour, groupable to 2/4/6 h | Every row carries **"DO NOT SELECT AN HOUR FROM THIS TABLE WITHOUT OOS CONFIRMATION"**. |
| **I · Long vs short** | The same, by direction | |
| **J · LLM council** | Agreement/disagreement, confidence, age; expectancy for quant-only, LLM-agree, LLM-disagree; **LLM VALUE** | VALUE is NONE unless the agree subset beats the disagree subset with non-overlapping CIs **and** beats quant-only, with n ≥ 100 each. Authority is always **NONE**. |
| **K · Latency/freshness** | p50/p90/p95/p99/max per stage, stale %, \|drift\|, spread, book-timestamp lag | Live measurements from shadow records; nothing hard-coded. |
| **L · Paper vs shadow** | Realised paper metrics vs the hypothetical gate-pass metrics; same-direction %; the four pass/trade overlap shares | Observational only. |
| **M · Cumulative shadow P&L** | Equity curve labelled **HYPOTHETICAL SHADOW — NOT REAL P&L** | Entry = real book mid at the execution point; exit = confirmed bar close at the horizon; measured cost per trade; one unit per candidate; no high/low fills. |
| **Daily** | Signals, gate passes, gross/net expectancy, cost, MFE/MAE per UTC day | For the 14-day run. |

**Anti-data-mining guards.** These are built in and cannot be switched off:

- Every statistic carries **⚠ INSUFFICIENT SAMPLE** (n < 100), **⚠ FEW INDEPENDENT BARS** (< 30) and **⚠ TOO FEW INDEPENDENT TIME BLOCKS** (< 5 two-hour blocks, in which case the t-stat and CI are deliberately blank: a t from 2 clusters is noise).
- The page shows **⚠ SINGLE WINDOW** until there are at least 2 days.
- Hour rows always carry the OOS warning.
- The dashboard has no "best subset" button. Selecting anything must go through `/research-lab`'s walk-forward framework, which records it in the registry.

## `/research-lab`

| Block | Shows |
|---|---|
| **Current research status** | **Deployable edge: NO / YES**. YES only if a non-seed experiment reached **ROBUST OOS EDGE**, and even then only "ACCEPTED_FOR_SHADOW". Also: best *verified* OOS net expectancy and PF, best experiment, horizon, sample, counts, last experiment. |
| **Next best research experiment** | The proposer's action: RUN, COLLECT_DATA, REPLICATE or STOP, with the exact data shortfall, and which hypotheses were skipped as already tested. |
| **Leaderboard** | Every experiment, including the seeded prior research, sorted by **OOS NET expectancy**. Never by training or validation score, AUC or win rate. |
| **Research failures** | Every REJECTED / OOS_FAILED experiment, so failed ideas stay visible and are not repeated. |
| **Data sufficiency** | Shadow observations, independent signal bars, days collected, 1-day OOS windows available, order-book, trade-flow and BTC coverage hours. |
| **Rules** | The framework's non-negotiables. |
