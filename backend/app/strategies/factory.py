"""Initial population DNA factory (spec section 11).

Generates diverse, valid StrategyDNA payloads across configurable strategy
families rather than 500 identical clones. Randomization is seeded so a
given (seed, index) always reproduces the same DNA — required for
reproducible research runs.
"""
from __future__ import annotations

import random
from collections.abc import Callable

from app.models.enums import MarketRegime, StrategyFamily
from app.strategies.engine import unknown_features
from app.schemas.strategy_dna import (
    ComparisonOperator,
    Condition,
    CooldownConfig,
    IndicatorConfig,
    PositionSizing,
    RiskProfile,
    RuleSet,
    StopLossConfig,
    StrategyDNA,
    TakeProfitConfig,
    TrailingStopConfig,
)

# Default population distribution across families (spec section 11). Must
# sum to 1.0; the remainder (if any) is absorbed by the last family.
DEFAULT_FAMILY_DISTRIBUTION: dict[StrategyFamily, float] = {
    StrategyFamily.MOMENTUM: 0.15,
    StrategyFamily.TREND_FOLLOWING: 0.15,
    StrategyFamily.BREAKOUT: 0.12,
    StrategyFamily.MEAN_REVERSION: 0.12,
    StrategyFamily.VOLATILITY: 0.10,
    StrategyFamily.MARKET_STRUCTURE: 0.10,
    StrategyFamily.VWAP: 0.08,
    StrategyFamily.SCALPING: 0.08,
    StrategyFamily.ORDER_FLOW: 0.05,
    StrategyFamily.HYBRID: 0.05,
}


def _family_builders() -> "dict[StrategyFamily, Callable[[random.Random], StrategyDNA]]":
    return {
        StrategyFamily.MOMENTUM: _build_momentum,
        StrategyFamily.TREND_FOLLOWING: _build_trend_following,
        StrategyFamily.BREAKOUT: _build_breakout,
        StrategyFamily.MEAN_REVERSION: _build_mean_reversion,
        StrategyFamily.VOLATILITY: _build_volatility,
        StrategyFamily.MARKET_STRUCTURE: _build_market_structure,
        StrategyFamily.VWAP: _build_vwap,
        StrategyFamily.SCALPING: _build_scalping,
        StrategyFamily.ORDER_FLOW: _build_order_flow,
        StrategyFamily.HYBRID: _build_hybrid,
    }


def _base_risk(rng: random.Random) -> RiskProfile:
    return RiskProfile(
        max_leverage=rng.choice([1.0, 2.0, 3.0, 5.0]),
        max_position_fraction=round(rng.uniform(0.05, 0.3), 3),
        max_daily_loss_fraction=round(rng.uniform(0.05, 0.15), 3),
        max_drawdown_fraction=round(rng.uniform(0.15, 0.35), 3),
    )


def _base_exits(rng: random.Random) -> tuple[StopLossConfig, TakeProfitConfig, TrailingStopConfig, CooldownConfig]:
    sl = StopLossConfig(method="atr_multiple", value=round(rng.uniform(1.2, 3.0), 2))
    tp = TakeProfitConfig(method="risk_reward_multiple", value=round(rng.uniform(1.5, 3.5), 2))
    trail = TrailingStopConfig(enabled=rng.random() < 0.4, activation_pct=round(rng.uniform(0.5, 2.0), 2), trail_pct=round(rng.uniform(0.3, 1.5), 2))
    cooldown = CooldownConfig(bars_after_loss=rng.randint(0, 10), bars_after_win=rng.randint(0, 3))
    return sl, tp, trail, cooldown


def _clamped_leverage(rng: random.Random, choices: list[float], risk: RiskProfile) -> float:
    """leverage_limit must never exceed risk_profile.max_leverage (enforced
    by StrategyDNA's validator) — sample independently, then clamp."""
    return min(rng.choice(choices), risk.max_leverage)


def _ind(name: str, **params) -> IndicatorConfig:
    return IndicatorConfig(name=name, params=params)


def _cond(feature: str, op: str, value) -> Condition:
    return Condition(feature=feature, operator=ComparisonOperator(op), value=value)


def _rules(logic: str, *conds: Condition) -> RuleSet:
    return RuleSet(logic=logic, conditions=list(conds))


def _finish(rng, family, indicators, long_entry, long_exit, short_entry, short_exit, regimes, *, mode="both",
            frac=(0.03, 0.1), trades=(5, 20), lev=(1.0, 2.0), sizing_method=None, exits=None):
    """Assembles a DNA whose rules reference ONLY the indicators it declares."""
    sl, tp, trail, cooldown = exits or _base_exits(rng)
    risk = _base_risk(rng)
    sizing = PositionSizing(
        method=sizing_method or rng.choice(["fraction_of_equity", "volatility_based", "risk_based", "fixed_fraction"]),
        fraction_of_equity=round(rng.uniform(*frac), 3),
    )
    dna = StrategyDNA(
        strategy_family=family,
        indicators=indicators,
        entry_rules=long_entry, exit_rules=long_exit,
        direction_mode=mode,
        short_entry_rules=short_entry if mode == "both" else None,
        short_exit_rules=short_exit if mode == "both" else None,
        regime_preferences=regimes,
        risk_profile=risk,
        position_sizing=sizing,
        stop_loss=sl, take_profit=tp, trailing_stop=trail, cooldown=cooldown,
        max_trades_per_day=rng.randint(*trades), leverage_limit=_clamped_leverage(rng, list(lev), risk),
    )
    bad = unknown_features(dna)
    if bad:  # a factory bug, never a runtime surprise
        raise ValueError(f"factory produced DNA with unresolved features {bad} for {family.value}")
    return dna


def _build_momentum(rng: random.Random) -> StrategyDNA:
    p, r, hi = rng.choice([7, 10, 14, 21]), rng.choice([5, 10, 20]), rng.choice([55, 60, 65])
    rsi, roc = f"rsi_{p}", f"roc_{r}"
    return _finish(
        rng, StrategyFamily.MOMENTUM, [_ind("rsi", period=p), _ind("roc", period=r)],
        _rules("AND", _cond(rsi, "gt", hi), _cond(roc, "gt", 0)), _rules("OR", _cond(rsi, "lt", 50)),
        _rules("AND", _cond(rsi, "lt", 100 - hi), _cond(roc, "lt", 0)), _rules("OR", _cond(rsi, "gt", 50)),
        [MarketRegime.TREND_UP, MarketRegime.TREND_DOWN, MarketRegime.BREAKOUT, MarketRegime.BREAKDOWN],
        trades=(5, 20), lev=(1.0, 2.0, 3.0),
    )


def _build_trend_following(rng: random.Random) -> StrategyDNA:
    f, sl_, adx_p = rng.choice([8, 12, 20]), rng.choice([34, 50, 100]), rng.choice([14, 20])
    fast, slow, adx = f"ema_{f}", f"ema_{sl_}", f"adx_{adx_p}"
    thr = rng.choice([18, 20, 25])
    return _finish(
        rng, StrategyFamily.TREND_FOLLOWING, [_ind("ema", period=f), _ind("ema", period=sl_), _ind("adx", period=adx_p)],
        _rules("AND", _cond(fast, "gt", slow), _cond(adx, "gt", thr)), _rules("OR", _cond(fast, "lt", slow)),
        _rules("AND", _cond(fast, "lt", slow), _cond(adx, "gt", thr)), _rules("OR", _cond(fast, "gt", slow)),
        [MarketRegime.TREND_UP, MarketRegime.TREND_DOWN], frac=(0.05, 0.15), trades=(3, 12), lev=(1.0, 2.0),
    )


def _build_breakout(rng: random.Random) -> StrategyDNA:
    n, vr = rng.choice([20, 30, 50]), rng.choice([1.1, 1.3, 1.6])
    m = max(5, n // 2)
    hi, lo, exit_ma = f"donchian_high_{n}", f"donchian_low_{n}", f"ema_{m}"
    return _finish(
        rng, StrategyFamily.BREAKOUT, [_ind("donchian", period=n), _ind("volume_ratio", period=20), _ind("ema", period=m)],
        _rules("AND", _cond("close", "gt", hi), _cond("volume_ratio_20", "gt", vr)), _rules("OR", _cond("close", "lt", exit_ma)),
        _rules("AND", _cond("close", "lt", lo), _cond("volume_ratio_20", "gt", vr)), _rules("OR", _cond("close", "gt", exit_ma)),
        [MarketRegime.BREAKOUT, MarketRegime.BREAKDOWN, MarketRegime.HIGH_VOLATILITY],
        frac=(0.05, 0.2), trades=(3, 15), lev=(1.0, 2.0, 3.0),
    )


def _build_mean_reversion(rng: random.Random) -> StrategyDNA:
    p, rp, lo_thr = rng.choice([14, 20, 30]), rng.choice([7, 14]), rng.choice([0.05, 0.1, 0.2])
    pct_b, rsi, mid = f"bb_pct_b_{p}", f"rsi_{rp}", f"bb_middle_{p}"
    rsi_lo = rng.choice([25, 30, 35])
    return _finish(
        rng, StrategyFamily.MEAN_REVERSION, [_ind("bbands", period=p), _ind("rsi", period=rp)],
        _rules("AND", _cond(pct_b, "lt", lo_thr), _cond(rsi, "lt", rsi_lo)), _rules("OR", _cond("close", "gt", mid)),
        _rules("AND", _cond(pct_b, "gt", 1 - lo_thr), _cond(rsi, "gt", 100 - rsi_lo)), _rules("OR", _cond("close", "lt", mid)),
        [MarketRegime.RANGE, MarketRegime.LOW_VOLATILITY], frac=(0.03, 0.12), trades=(5, 25), lev=(1.0, 2.0),
    )


def _build_volatility(rng: random.Random) -> StrategyDNA:
    p, w = rng.choice([14, 20]), rng.choice([0.012, 0.018, 0.025])
    width = f"bb_width_{p}"
    return _finish(
        rng, StrategyFamily.VOLATILITY, [_ind("bbands", period=p), _ind("atr", period=p), _ind("volume_ratio", period=20)],
        _rules("AND", _cond(width, "gt", w), _cond("volume_ratio_20", "gt", rng.choice([1.2, 1.5])),
               _cond("volatility_percentile", "gt", 0.7)),
        _rules("OR", _cond(width, "lt", round(w * 0.7, 4))),
        None, None, [MarketRegime.HIGH_VOLATILITY, MarketRegime.BREAKOUT, MarketRegime.BREAKDOWN],
        mode="auto", frac=(0.02, 0.08), trades=(3, 15), lev=(1.0, 2.0),
    )


def _build_market_structure(rng: random.Random) -> StrategyDNA:
    n = rng.choice([10, 20, 40])
    return _finish(
        rng, StrategyFamily.MARKET_STRUCTURE, [_ind("swing", period=n), _ind("atr", period=14)],
        _rules("AND", _cond("higher_high", "gt", 0.5), _cond("higher_low", "gt", 0.5)), _rules("OR", _cond("lower_high", "gt", 0.5)),
        _rules("AND", _cond("lower_high", "gt", 0.5), _cond("lower_low", "gt", 0.5)), _rules("OR", _cond("higher_low", "gt", 0.5)),
        [MarketRegime.TREND_UP, MarketRegime.TREND_DOWN, MarketRegime.RANGE], frac=(0.05, 0.15), trades=(3, 12), lev=(1.0, 2.0),
    )


def _build_vwap(rng: random.Random) -> StrategyDNA:
    period = rng.choice([0, 60, 120])
    dev = "vwap_dev_session" if period == 0 else f"vwap_dev_{period}"
    d = rng.choice([0.002, 0.004, 0.007])
    return _finish(
        rng, StrategyFamily.VWAP, [_ind("vwap", period=period)],
        _rules("AND", _cond(dev, "lt", -d)), _rules("OR", _cond(dev, "gt", 0)),
        _rules("AND", _cond(dev, "gt", d)), _rules("OR", _cond(dev, "lt", 0)),
        [MarketRegime.RANGE, MarketRegime.LOW_VOLATILITY, MarketRegime.TREND_UP, MarketRegime.TREND_DOWN],
        frac=(0.05, 0.15), trades=(5, 20), lev=(1.0, 2.0),
    )


def _build_scalping(rng: random.Random) -> StrategyDNA:
    e, r = rng.choice([5, 9, 13]), rng.choice([3, 5])
    ema, roc, rsi = f"ema_{e}", f"roc_{r}", "rsi_7"
    thr = rng.choice([0.03, 0.05, 0.1])
    exits = (StopLossConfig(method="atr_multiple", value=round(rng.uniform(0.8, 1.5), 2)),
             TakeProfitConfig(method="risk_reward_multiple", value=round(rng.uniform(1.0, 1.8), 2)),
             TrailingStopConfig(enabled=rng.random() < 0.4, activation_pct=round(rng.uniform(0.2, 0.6), 2), trail_pct=round(rng.uniform(0.15, 0.5), 2)),
             CooldownConfig(bars_after_loss=rng.randint(0, 5), bars_after_win=rng.randint(0, 2)))
    return _finish(
        rng, StrategyFamily.SCALPING, [_ind("ema", period=e), _ind("roc", period=r), _ind("rsi", period=7)],
        _rules("AND", _cond(roc, "gt", thr), _cond("close", "gt", ema), _cond("is_momentum_candle", "gt", 0.5)),
        _rules("OR", _cond(rsi, "gt", 75), _cond("close", "lt", ema)),
        _rules("AND", _cond(roc, "lt", -thr), _cond("close", "lt", ema), _cond("is_momentum_candle", "gt", 0.5)),
        _rules("OR", _cond(rsi, "lt", 25), _cond("close", "gt", ema)),
        [], frac=(0.02, 0.06), trades=(20, 80), lev=(1.0, 2.0, 3.0), exits=exits,
    )


def _build_order_flow(rng: random.Random) -> StrategyDNA:
    p, thr = rng.choice([5, 10, 20]), rng.choice([0.2, 0.3, 0.45])
    flow = f"flow_imbalance_{p}"
    return _finish(
        rng, StrategyFamily.ORDER_FLOW, [_ind("flow_imbalance", period=p), _ind("volume_ratio", period=20)],
        _rules("AND", _cond(flow, "gt", thr), _cond("volume_ratio_20", "gt", rng.choice([1.1, 1.4]))), _rules("OR", _cond(flow, "lt", 0)),
        _rules("AND", _cond(flow, "lt", -thr), _cond("volume_ratio_20", "gt", rng.choice([1.1, 1.4]))), _rules("OR", _cond(flow, "gt", 0)),
        [MarketRegime.BREAKOUT, MarketRegime.BREAKDOWN, MarketRegime.HIGH_VOLATILITY, MarketRegime.TREND_UP, MarketRegime.TREND_DOWN],
        frac=(0.03, 0.1), trades=(5, 20), lev=(1.0, 2.0),
    )


def _build_hybrid(rng: random.Random) -> StrategyDNA:
    e, rp = rng.choice([34, 50, 100]), rng.choice([10, 14, 21])
    ema, rsi = f"ema_{e}", f"rsi_{rp}"
    return _finish(
        rng, StrategyFamily.HYBRID, [_ind("ema", period=e), _ind("rsi", period=rp), _ind("atr", period=14)],
        _rules("AND", _cond("close", "gt", ema), _cond(rsi, "gt", 50), _cond("macd_hist", "gt", 0)), _rules("OR", _cond(rsi, "lt", 45)),
        _rules("AND", _cond("close", "lt", ema), _cond(rsi, "lt", 50), _cond("macd_hist", "lt", 0)), _rules("OR", _cond(rsi, "gt", 55)),
        [], frac=(0.03, 0.1), trades=(5, 20), lev=(1.0, 2.0),
    )


def generate_population_dna(
    count: int,
    distribution: dict[StrategyFamily, float] | None = None,
    seed: int = 42,
) -> list[StrategyDNA]:
    """Deterministically generates `count` diverse StrategyDNA payloads
    according to `distribution` (fractions summing to ~1.0)."""
    dist = distribution or DEFAULT_FAMILY_DISTRIBUTION
    builders = _family_builders()
    families = list(dist.keys())
    weights = list(dist.values())

    rng = random.Random(seed)
    result: list[StrategyDNA] = []
    for i in range(count):
        family = rng.choices(families, weights=weights, k=1)[0]
        agent_rng = random.Random(seed * 1_000_003 + i)
        result.append(builders[family](agent_rng))
    return result
