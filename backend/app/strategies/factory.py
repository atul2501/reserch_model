"""Initial population DNA factory (spec section 11).

Generates diverse, valid StrategyDNA payloads across configurable strategy
families rather than 500 identical clones. Randomization is seeded so a
given (seed, index) always reproduces the same DNA — required for
reproducible research runs.
"""
from __future__ import annotations

import random

from app.models.enums import MarketRegime, StrategyFamily
from app.schemas.strategy_dna import (
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


def _family_builders() -> dict[StrategyFamily, callable]:
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


def _build_momentum(rng: random.Random) -> StrategyDNA:
    period = rng.choice([10, 14, 21])
    sl, tp, trail, cooldown = _base_exits(rng)
    risk = _base_risk(rng)
    return StrategyDNA(
        strategy_family=StrategyFamily.MOMENTUM,
        indicators=[IndicatorConfig(name="rsi", params={"period": period}), IndicatorConfig(name="roc", params={"period": 10})],
        entry_rules=RuleSet(logic="AND", conditions=[Condition(feature="rsi_14", operator="gt", value=rng.choice([55, 60, 65]))]),
        exit_rules=RuleSet(logic="OR", conditions=[Condition(feature="rsi_14", operator="lt", value=50)]),
        regime_preferences=[MarketRegime.TREND_UP, MarketRegime.BREAKOUT],
        risk_profile=risk,
        position_sizing=PositionSizing(fraction_of_equity=round(rng.uniform(0.03, 0.1), 3)),
        stop_loss=sl, take_profit=tp, trailing_stop=trail, cooldown=cooldown,
        max_trades_per_day=rng.randint(5, 20), leverage_limit=_clamped_leverage(rng, [1.0, 2.0, 3.0], risk),
    )


def _build_trend_following(rng: random.Random) -> StrategyDNA:
    sl, tp, trail, cooldown = _base_exits(rng)
    risk = _base_risk(rng)
    return StrategyDNA(
        strategy_family=StrategyFamily.TREND_FOLLOWING,
        indicators=[IndicatorConfig(name="ema", params={"period": 12}), IndicatorConfig(name="ema", params={"period": 50})],
        entry_rules=RuleSet(logic="AND", conditions=[Condition(feature="ema_fast", operator="crosses_above", value="ema_slow")]),
        exit_rules=RuleSet(logic="OR", conditions=[Condition(feature="ema_fast", operator="crosses_below", value="ema_slow")]),
        regime_preferences=[MarketRegime.TREND_UP, MarketRegime.TREND_DOWN],
        risk_profile=risk,
        position_sizing=PositionSizing(fraction_of_equity=round(rng.uniform(0.05, 0.15), 3)),
        stop_loss=sl, take_profit=tp, trailing_stop=trail, cooldown=cooldown,
        max_trades_per_day=rng.randint(3, 12), leverage_limit=_clamped_leverage(rng, [1.0, 2.0], risk),
    )


def _build_breakout(rng: random.Random) -> StrategyDNA:
    sl, tp, trail, cooldown = _base_exits(rng)
    risk = _base_risk(rng)
    return StrategyDNA(
        strategy_family=StrategyFamily.BREAKOUT,
        indicators=[IndicatorConfig(name="atr", params={"period": 14}), IndicatorConfig(name="bbands", params={"period": 20})],
        entry_rules=RuleSet(logic="AND", conditions=[Condition(feature="break_of_structure", operator="gt", value=0.5)]),
        exit_rules=RuleSet(logic="OR", conditions=[Condition(feature="bb_width", operator="lt", value=0.015)]),
        regime_preferences=[MarketRegime.BREAKOUT, MarketRegime.BREAKDOWN],
        risk_profile=risk,
        position_sizing=PositionSizing(fraction_of_equity=round(rng.uniform(0.05, 0.2), 3)),
        stop_loss=sl, take_profit=tp, trailing_stop=trail, cooldown=cooldown,
        max_trades_per_day=rng.randint(3, 15), leverage_limit=_clamped_leverage(rng, [1.0, 2.0, 3.0], risk),
    )


def _build_mean_reversion(rng: random.Random) -> StrategyDNA:
    sl, tp, trail, cooldown = _base_exits(rng)
    risk = _base_risk(rng)
    return StrategyDNA(
        strategy_family=StrategyFamily.MEAN_REVERSION,
        indicators=[IndicatorConfig(name="rsi", params={"period": 14}), IndicatorConfig(name="bbands", params={"period": 20})],
        entry_rules=RuleSet(logic="AND", conditions=[Condition(feature="rsi_14", operator="lt", value=rng.choice([25, 30, 35]))]),
        exit_rules=RuleSet(logic="OR", conditions=[Condition(feature="rsi_14", operator="gt", value=50)]),
        regime_preferences=[MarketRegime.RANGE, MarketRegime.LOW_VOLATILITY],
        risk_profile=risk,
        position_sizing=PositionSizing(fraction_of_equity=round(rng.uniform(0.03, 0.12), 3)),
        stop_loss=sl, take_profit=tp, trailing_stop=trail, cooldown=cooldown,
        max_trades_per_day=rng.randint(5, 25), leverage_limit=_clamped_leverage(rng, [1.0, 2.0], risk),
    )


def _build_volatility(rng: random.Random) -> StrategyDNA:
    sl, tp, trail, cooldown = _base_exits(rng)
    risk = _base_risk(rng)
    return StrategyDNA(
        strategy_family=StrategyFamily.VOLATILITY,
        indicators=[IndicatorConfig(name="atr", params={"period": 14})],
        entry_rules=RuleSet(logic="AND", conditions=[Condition(feature="volatility_percentile", operator="gt", value=0.7)]),
        exit_rules=RuleSet(logic="OR", conditions=[Condition(feature="volatility_percentile", operator="lt", value=0.4)]),
        regime_preferences=[MarketRegime.HIGH_VOLATILITY],
        risk_profile=risk,
        position_sizing=PositionSizing(fraction_of_equity=round(rng.uniform(0.02, 0.08), 3)),
        stop_loss=sl, take_profit=tp, trailing_stop=trail, cooldown=cooldown,
        max_trades_per_day=rng.randint(3, 15), leverage_limit=_clamped_leverage(rng, [1.0, 2.0], risk),
    )


def _build_market_structure(rng: random.Random) -> StrategyDNA:
    sl, tp, trail, cooldown = _base_exits(rng)
    risk = _base_risk(rng)
    return StrategyDNA(
        strategy_family=StrategyFamily.MARKET_STRUCTURE,
        indicators=[IndicatorConfig(name="swing", params={"window": 5})],
        entry_rules=RuleSet(logic="AND", conditions=[Condition(feature="higher_low", operator="gt", value=0.5)]),
        exit_rules=RuleSet(logic="OR", conditions=[Condition(feature="lower_high", operator="gt", value=0.5)]),
        regime_preferences=[MarketRegime.TREND_UP, MarketRegime.RANGE],
        risk_profile=risk,
        position_sizing=PositionSizing(fraction_of_equity=round(rng.uniform(0.05, 0.15), 3)),
        stop_loss=sl, take_profit=tp, trailing_stop=trail, cooldown=cooldown,
        max_trades_per_day=rng.randint(3, 12), leverage_limit=_clamped_leverage(rng, [1.0, 2.0], risk),
    )


def _build_vwap(rng: random.Random) -> StrategyDNA:
    sl, tp, trail, cooldown = _base_exits(rng)
    risk = _base_risk(rng)
    return StrategyDNA(
        strategy_family=StrategyFamily.VWAP,
        indicators=[IndicatorConfig(name="vwap", params={})],
        entry_rules=RuleSet(logic="AND", conditions=[Condition(feature="close", operator="gt", value="vwap")]),
        exit_rules=RuleSet(logic="OR", conditions=[Condition(feature="close", operator="lt", value="vwap")]),
        regime_preferences=[MarketRegime.TREND_UP, MarketRegime.RANGE],
        risk_profile=risk,
        position_sizing=PositionSizing(fraction_of_equity=round(rng.uniform(0.05, 0.15), 3)),
        stop_loss=sl, take_profit=tp, trailing_stop=trail, cooldown=cooldown,
        max_trades_per_day=rng.randint(5, 20), leverage_limit=_clamped_leverage(rng, [1.0, 2.0], risk),
    )


def _build_scalping(rng: random.Random) -> StrategyDNA:
    sl, tp, trail, cooldown = _base_exits(rng)
    risk = _base_risk(rng)
    return StrategyDNA(
        strategy_family=StrategyFamily.SCALPING,
        indicators=[IndicatorConfig(name="rsi", params={"period": 7}), IndicatorConfig(name="ema", params={"period": 9})],
        entry_rules=RuleSet(logic="AND", conditions=[Condition(feature="is_momentum_candle", operator="gt", value=0.5)]),
        exit_rules=RuleSet(logic="OR", conditions=[Condition(feature="rsi_14", operator="gt", value=70)]),
        regime_preferences=[],
        risk_profile=risk,
        position_sizing=PositionSizing(fraction_of_equity=round(rng.uniform(0.02, 0.06), 3)),
        stop_loss=StopLossConfig(method="atr_multiple", value=round(rng.uniform(0.8, 1.5), 2)),
        take_profit=TakeProfitConfig(method="risk_reward_multiple", value=round(rng.uniform(1.0, 1.8), 2)),
        trailing_stop=trail, cooldown=cooldown,
        max_trades_per_day=rng.randint(20, 80), leverage_limit=_clamped_leverage(rng, [1.0, 2.0, 3.0], risk),
    )


def _build_order_flow(rng: random.Random) -> StrategyDNA:
    sl, tp, trail, cooldown = _base_exits(rng)
    risk = _base_risk(rng)
    return StrategyDNA(
        strategy_family=StrategyFamily.ORDER_FLOW,
        indicators=[IndicatorConfig(name="volume_ratio", params={"period": 20})],
        entry_rules=RuleSet(logic="AND", conditions=[Condition(feature="volume_spike", operator="gt", value=0.5)]),
        exit_rules=RuleSet(logic="OR", conditions=[Condition(feature="volume_ratio", operator="lt", value=1.0)]),
        regime_preferences=[MarketRegime.BREAKOUT, MarketRegime.HIGH_VOLATILITY],
        risk_profile=risk,
        position_sizing=PositionSizing(fraction_of_equity=round(rng.uniform(0.03, 0.1), 3)),
        stop_loss=sl, take_profit=tp, trailing_stop=trail, cooldown=cooldown,
        max_trades_per_day=rng.randint(5, 20), leverage_limit=_clamped_leverage(rng, [1.0, 2.0], risk),
    )


def _build_hybrid(rng: random.Random) -> StrategyDNA:
    sl, tp, trail, cooldown = _base_exits(rng)
    risk = _base_risk(rng)
    return StrategyDNA(
        strategy_family=StrategyFamily.HYBRID,
        indicators=[
            IndicatorConfig(name="rsi", params={"period": 14}),
            IndicatorConfig(name="ema", params={"period": 50}),
            IndicatorConfig(name="atr", params={"period": 14}),
        ],
        entry_rules=RuleSet(
            logic="AND",
            conditions=[
                Condition(feature="trend_strength", operator="gt", value=0),
                Condition(feature="rsi_14", operator="gt", value=50),
            ],
        ),
        exit_rules=RuleSet(logic="OR", conditions=[Condition(feature="rsi_14", operator="lt", value=45)]),
        regime_preferences=[],
        risk_profile=risk,
        position_sizing=PositionSizing(fraction_of_equity=round(rng.uniform(0.03, 0.1), 3)),
        stop_loss=sl, take_profit=tp, trailing_stop=trail, cooldown=cooldown,
        max_trades_per_day=rng.randint(5, 20), leverage_limit=_clamped_leverage(rng, [1.0, 2.0], risk),
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
