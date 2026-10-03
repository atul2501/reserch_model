# Prompt / LLM Audit

Source: `backend/app/council/analysts.py`, `council/service.py`, `council/consensus.py`, `council/context.py`, `worker/cycle.py`.
Model in production: `gpt-oss:120b` via the Ollama API.

## 1. The exact production prompt

**System prompt.** It is the same for all 8 analysts; only `{analyst}` and `{focus}` change.

```
You are the {analyst} analyst on a professional crypto trading research council.
Your job: {focus}

You will be given a structured market feature snapshot for a single SOL perpetual
futures candle. Respond with ONLY a JSON object matching this schema:
{
  "analyst": "{analyst}",
  "bias": "LONG" | "SHORT" | "NEUTRAL",
  "confidence": <float 0.0-1.0>,
  "reasoning": "<concise reasoning, 1-3 sentences>",
  "key_factors": ["<factor1>", "..."],
  "invalidators": ["<what would prove this wrong>", "..."]
}
key_factors and invalidators: AT MOST 10 items each, ordered MOST IMPORTANT FIRST.
Do not include any text outside the JSON object. Be honest about uncertainty —
low confidence and NEUTRAL are valid, useful answers.
```

**Focus strings** (`ANALYST_FOCUS`):

| Analyst | Focus |
|---|---|
| trend | "Assess directional trend strength using EMA/SMA alignment and slope. Ignore short-term noise." |
| momentum | "Assess momentum using RSI, MACD, and rate of change. Flag overbought/oversold extremes." |
| structure | "Assess market structure: swing highs/lows, breaks of structure, support/resistance proximity." |
| order_flow | "Assess volume and participation: volume spikes, VWAP relationship, and what they imply about conviction." |
| volatility | "Assess volatility regime using ATR, realized volatility, and Bollinger Band width. Flag abnormal conditions." |
| regime | "Assess the current market regime classification and whether price action confirms or contradicts it." |
| risk | "Assess downside risk: what could invalidate a position right now, and how far away is invalidation." |
| contrarian | "Actively look for reasons the obvious read is wrong. Argue the counter-case even if unpopular." |

**User prompt:**

```
Market: SOL 1m
Candle open time: <epoch ms>
Close price: <float>
Regime: <REGIME> (confidence <x.xx>)
Features: <Python dict repr of MarketContext.flat_features()>
```

The `Features` dict holds one bar's values for:
- EMA/SMA fast/slow, ema_slope, trend_strength;
- RSI14, MACD/signal/hist, ROC10;
- ATR14, realized vol, volatility percentile, Bollinger bands/width;
- swing high/low and HH/HL/LH/LL flags, break of structure, nearest support/resistance;
- volume SMA20, volume ratio, volume spike, window VWAP;
- body, wick ratio, range, gap, momentum-candle flag;
- funding rate and open interest.

When analysts disagree (vote lead < 2), a judge prompt receives the analyses and "prefer[s] NEUTRAL over a low-confidence directional call."

## 2. What the model receives — and what it does not

| Question | Answer |
|---|---|
| Current position? | **No.** The council runs once per bar for the whole population, before any agent. |
| Fees / slippage? | **No.** |
| Minimum profitable move (~13.5 bps round trip)? | **No.** |
| Expected holding horizon? | **No.** It is never told whether "LONG" means 1 minute or 1 hour. |
| Market regime? | Yes: the rule-based label and its confidence. |
| Raw candles / price history? | **No.** It sees one bar: the latest close plus derived indicators. No sequence, no prior bars. |
| Derived indicators? | Yes. About 40 numbers, unlabelled for units (for example `roc_10` is in percent and `atr_14` is in dollars). |
| Order flow? | Only a volume ratio and the window VWAP. No trades/tape, no book, no bid/ask. |
| Confidence of the agent's own signal? | **No.** The council never sees which agents want to trade, or which way. |
| Contradictory signals? | Yes, typically: for example EMA alignment up, MACD and ROC down. See the example below. |
| Enough history? | **No.** It gets one snapshot. Momentum, structure and trend are pre-digested into single numbers. |
| Is the requested quantity learnable? | **No.** Direction of SOL over an *unspecified* horizon from one 1m snapshot of public indicators is the same question the DNA rules already answer, with the same inputs and no edge (see Phase 2). |

## 3. The model's actual role

- **It does not choose trades, strategies or direction for agents.** Agent DNA rules decide whether a setup exists and which way to trade it.
- **It runs only on every 5th candle** (`COUNCIL_INTERVAL_CANDLES=5`). On the other 80% of candles, entries proceed with `council_not_required` and a size modifier of 1.0. Of 43,287 clean trades, 35,781 (83%) had no council input.
- **On council candles, `council/context.combine` can only:**
  - (a) **veto** an opposed entry when council confidence ≥ 0.60;
  - (b) **scale size**: aligned ×(1 + 0.15·conf); NEUTRAL ×0.75; opposed below 0.60 ×(1 − 0.5·conf);
  - (c) **block all entries** if INCOMPLETE (quorum < 6 of 8). That never happened in this backup: 1,488 of 1,488 councils were COMPLETE.
- **Parsing and failure handling look correct.**
  - Pydantic schema validation is used, and an analyst whose response names another analyst is rejected.
  - Failed or late analysts are cancelled and counted as abstaining.
  - There is no silent default to LONG or SHORT: a failure is NEUTRAL with `trade_allowed=False` (fail closed).
  - 11,901 of 11,904 analyses were valid; 3 timed out at 44s.
- **Tie handling.** `compute_consensus` sorts the tally. On a tie the top bias is whichever key sorts first, but a tie is never "strong", so the judge is invoked (409 times) or the council abstains. No bug found here.

## 4. Measured value of the LLM (`forensic.py` section 5)

**Council directional calls** (n = 817 LONG/SHORT finals), signed forward return from the next bar open:

| Horizon | Mean | Directional accuracy | Cluster t |
|---|--:|--:|--:|
| 5m | +0.45 bps | 48.2% | 0.64 |
| 30m | +0.69 bps | 48.3% | 0.26 |
| 60m | +0.66 bps | 46.1% | 0.17 |

High-confidence calls (≥ 0.6, n = 303) returned +1.30 bps at 30m (t = 0.32).

**Vetoes.** The 168 signals the council vetoed would have earned +4.55 bps at 30m (t = 0.88). The vetoes did not remove losers.

**Trades by council reason (net bps):**

| Council reason | Net bps |
|---|--:|
| aligned | −11.2 |
| neutral | −14.6 |
| not_required | −13.5 |
| opposed_reduced | −12.5 |

These differences are within noise, and all are far below breakeven.

**Example council** (latest LONG final). Every analyst restates the same handful of indicator values and reaches a different direction:
- trend: "Fast EMA and SMA are both above … However, MACD histogram, ROC and lower low are bearish" → LONG 0.57.
- momentum: "MACD histogram is negative and ROC10 shows a slight decline" → SHORT 0.57.
- contrarian → SHORT 0.66.
- order_flow: "closed well above VWAP" → LONG 0.62.

The vote is effectively a re-weighting of the same features the DNA rules use.

**Analyst behaviour:**
- The "contrarian" analyst answered NEUTRAL 0 times in 1,488 councils (841 LONG / 647 SHORT). Its instruction forces a directional counter-case.
- Overall, the analysts lean SHORT, consistent with the falling SOL price in the sample.

## 5. Prompt-quality findings

1. **No economic framing.** There is no cost, no horizon, no minimum expected move and no risk/reward requirement. The model cannot know that a "LONG" needs more than about 13.5 bps to be worth taking.
2. **No new information.** Every input is a deterministic function of the same OHLCV the strategies already use. An LLM cannot recover information the inputs do not contain.
3. **Single-bar snapshot.** There is no sequence context, so the model cannot reason about path, persistence or acceleration beyond what the pre-computed indicators encode.
4. **Units not explained.** For example `roc_10=-0.17` means −0.17%, `atr_14=0.13` is in USD, and `trend_strength` is a fraction.
5. **The "contrarian" role is structurally biased** against NEUTRAL.
6. **Explicit HOLD criteria are absent.** NEUTRAL is allowed but never defined.

**Conclusion.** Could a competent quantitative trader make a statistically informed 1-minute SOL decision from this snapshot? **No.** The edge is not in these inputs; Phase 2 shows the information content is approximately zero. Improving the wording would not change that. **The prompt is a weakness, not the cause of the losses.** The council touches only 17% of trades, its effect is not statistically distinguishable from zero in either direction, and removing it entirely would leave expectancy at about −13 bps.
