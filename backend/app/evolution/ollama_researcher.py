"""Ollama-driven strategy research (spec section 26).

Ollama proposes candidate DNA; it never becomes a live strategy directly.
Every candidate returned here must still pass:
  schema validation (done here, via Pydantic) -> backtest -> walk-forward ->
  out-of-sample -> candidate approval -> agent creation.
"""
from __future__ import annotations

import json

from app.schemas.strategy_dna import StrategyCandidate
from app.services.ollama_client import OllamaClient, OllamaResponseError

_SYSTEM_PROMPT = """You are the evolutionary research analyst for a crypto trading
strategy laboratory. You will be given a summary of recent population
performance, failure modes, and market regime behavior. Propose ONE new
candidate trading strategy that addresses a gap in the current population.

Respond with ONLY a JSON object matching this schema:
{
  "strategy_family": "momentum"|"trend_following"|"breakout"|"mean_reversion"|"volatility"|"market_structure"|"vwap"|"scalping"|"order_flow"|"hybrid",
  "hypothesis": "<why this should work>",
  "dna": {
    "strategy_family": "<same as above>",
    "indicators": [{"name": "<indicator>", "params": {}}],
    "lookback_periods": {},
    "entry_rules": {"logic": "AND"|"OR", "conditions": [{"feature": "<feature_name>", "operator": "gt"|"lt"|"gte"|"lte"|"crosses_above"|"crosses_below", "value": <number>}]},
    "exit_rules": {"logic": "AND"|"OR", "conditions": [{"feature": "<feature_name>", "operator": "gt"|"lt"|"gte"|"lte"|"crosses_above"|"crosses_below", "value": <number>}]},
    "regime_preferences": ["TREND_UP"|"TREND_DOWN"|"RANGE"|"HIGH_VOLATILITY"|"LOW_VOLATILITY"|"BREAKOUT"|"BREAKDOWN"|"UNCERTAIN"],
    "risk_profile": {"max_leverage": <1-20>, "max_position_fraction": <0.01-1.0>, "max_daily_loss_fraction": <0.01-1.0>, "max_drawdown_fraction": <0.05-1.0>},
    "position_sizing": {"method": "fixed_fraction", "fraction_of_equity": <0.001-1.0>},
    "stop_loss": {"enabled": true, "method": "atr_multiple", "value": <positive number>},
    "take_profit": {"enabled": true, "method": "risk_reward_multiple", "value": <positive number>},
    "trailing_stop": {"enabled": false, "activation_pct": 0, "trail_pct": 0},
    "cooldown": {"bars_after_loss": 0, "bars_after_win": 0},
    "max_trades_per_day": <1-1000>,
    "leverage_limit": <1-20, must be <= risk_profile.max_leverage>
  },
  "expected_behavior": "<what this should do in which regimes>",
  "failure_conditions": ["<condition under which this strategy should be expected to fail>"]
}
Available feature names: close, ema_fast, ema_slow, sma_fast, sma_slow, ema_slope,
trend_strength, rsi_14, macd, macd_signal, macd_hist, roc_10, atr_14, realized_vol,
volatility_percentile, bb_upper, bb_middle, bb_lower, bb_width, swing_high, swing_low,
break_of_structure, higher_high, lower_high, higher_low, lower_low, nearest_support,
nearest_resistance, volume_sma_20, volume_ratio, volume_spike, vwap, body, wick_ratio,
candle_range, gap, is_momentum_candle, regime_confidence.
Do not include any text outside the JSON object."""


async def propose_candidate(client: OllamaClient, research_summary: dict) -> StrategyCandidate | None:
    """Returns None if Ollama's proposal fails schema validation — the
    caller must never fall back to inserting an unvalidated payload."""
    user_prompt = f"Population research summary:\n{json.dumps(research_summary, default=str, indent=2)}"
    try:
        candidate, _stats = await client.generate_structured(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_model=StrategyCandidate,
            temperature=0.6,
        )
        return candidate
    except OllamaResponseError:
        return None
