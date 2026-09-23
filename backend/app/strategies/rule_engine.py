"""Backward-compatible facade over `app.strategies.engine`.

`evaluate(dna, context, prev_context, has_open_position)` is kept so callers
that only hold a MarketContext (backtest engine, older tests) keep working;
new code builds a FeatureView with population-wide dynamic indicators and
calls `engine.evaluate_signal` directly.
"""
from __future__ import annotations

from app.models.enums import Side
from app.schemas.market_context import MarketContext
from app.schemas.strategy_dna import StrategyDNA
from app.strategies.engine import Signal, build_feature_view, evaluate_signal

SignalResult = Signal


def evaluate(
    dna: StrategyDNA,
    context: MarketContext,
    prev_context: MarketContext | None = None,
    has_open_position: bool = False,
    *,
    position_side: Side | None = None,
    dynamic_current: dict | None = None,
    dynamic_previous: dict | None = None,
) -> Signal:
    view = build_feature_view(context, prev_context, dynamic_current, dynamic_previous)
    side = position_side if position_side is not None else (Side.LONG if has_open_position else None)
    return evaluate_signal(dna, view, position_side=side)
