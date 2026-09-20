"""Deterministic Risk Engine (spec section 18).

Ollama cannot override this. Every proposed trade passes through here and
comes out APPROVED, REDUCED, or REJECTED with a reason. This is the final
safety authority before execution.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.models.agent import Agent
from app.models.enums import RiskDecision, Side
from app.schemas.strategy_dna import StrategyDNA

MAX_STALE_DATA_SECONDS = 180
ABNORMAL_VOLATILITY_ATR_PCT_THRESHOLD = 0.08  # ATR as % of price


@dataclass
class RiskCheckInput:
    agent: Agent
    dna: StrategyDNA
    side: Side
    proposed_notional: float
    proposed_leverage: float
    current_price: float
    atr: float
    equity: float
    daily_pnl: float
    has_open_position: bool
    market_data_age_seconds: float | None
    liquidation_distance_pct: float | None = None


@dataclass
class RiskCheckResult:
    decision: RiskDecision
    approved_notional: float
    approved_leverage: float
    reasons: list[str] = field(default_factory=list)


def check_trade(inp: RiskCheckInput, *, global_max_leverage: float, global_max_position_size: float,
                 global_max_drawdown: float, global_max_daily_loss: float) -> RiskCheckResult:
    reasons: list[str] = []

    # Hard blockers — reject outright, no reduction possible.
    if inp.market_data_age_seconds is not None and inp.market_data_age_seconds > MAX_STALE_DATA_SECONDS:
        return RiskCheckResult(RiskDecision.REJECTED, 0.0, 0.0, ["stale_market_data"])

    if inp.equity <= 0:
        return RiskCheckResult(RiskDecision.REJECTED, 0.0, 0.0, ["non_positive_equity"])

    current_drawdown = _drawdown_fraction(inp.agent)
    if current_drawdown >= min(inp.dna.risk_profile.max_drawdown_fraction, global_max_drawdown):
        return RiskCheckResult(RiskDecision.REJECTED, 0.0, 0.0, ["max_drawdown_exceeded"])

    daily_loss_fraction = max(0.0, -inp.daily_pnl / inp.agent.starting_balance)
    if daily_loss_fraction >= min(inp.dna.risk_profile.max_daily_loss_fraction, global_max_daily_loss):
        return RiskCheckResult(RiskDecision.REJECTED, 0.0, 0.0, ["max_daily_loss_exceeded"])

    if inp.has_open_position:
        return RiskCheckResult(RiskDecision.REJECTED, 0.0, 0.0, ["duplicate_position_not_allowed"])

    atr_pct = inp.atr / inp.current_price if inp.current_price else 0.0
    if atr_pct > ABNORMAL_VOLATILITY_ATR_PCT_THRESHOLD:
        return RiskCheckResult(RiskDecision.REJECTED, 0.0, 0.0, ["abnormal_volatility"])

    if inp.liquidation_distance_pct is not None and inp.liquidation_distance_pct < 0.02:
        return RiskCheckResult(RiskDecision.REJECTED, 0.0, 0.0, ["liquidation_distance_too_close"])

    # Soft blockers — reduce size/leverage to fit within limits.
    leverage = min(inp.proposed_leverage, inp.dna.leverage_limit, inp.dna.risk_profile.max_leverage, global_max_leverage)
    if leverage < inp.proposed_leverage:
        reasons.append("leverage_reduced_to_limit")

    max_notional_by_fraction = inp.equity * min(inp.dna.risk_profile.max_position_fraction, global_max_position_size)
    notional = min(inp.proposed_notional, max_notional_by_fraction)
    if inp.dna.position_sizing.max_notional is not None:
        notional = min(notional, inp.dna.position_sizing.max_notional)
    if notional < inp.proposed_notional:
        reasons.append("position_size_reduced_to_limit")

    if notional <= 0:
        return RiskCheckResult(RiskDecision.REJECTED, 0.0, 0.0, reasons + ["zero_notional_after_reduction"])

    decision = RiskDecision.REDUCED if reasons else RiskDecision.APPROVED
    return RiskCheckResult(decision, notional, leverage, reasons)


def _drawdown_fraction(agent: Agent) -> float:
    if agent.peak_equity <= 0:
        return 0.0
    return max(0.0, (agent.peak_equity - agent.equity) / agent.peak_equity)
