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
    # Fail-closed gate: False when this candle's council cycle was
    # INCOMPLETE (quorum not met) or otherwise marked unsafe upstream. The
    # Risk Engine is the single place this is actually enforced — callers
    # must never skip invoking check_trade just because they already know
    # the council failed (spec: "do not bypass the Risk Engine").
    council_trade_allowed: bool = True
    # Non-None when the system is halted for new entries (operator kill
    # switch, unrecoverable market-data gap...). Exits are never blocked.
    trading_halt_reason: str | None = None
    # Margin the agent can still commit (equity - used margin). When given,
    # required margin (notional / leverage) may never exceed it.
    available_margin: float | None = None
    # Fractional distance from entry to the protective stop (None => no stop known).
    stop_distance_pct: float | None = None


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
    if inp.trading_halt_reason:
        return RiskCheckResult(RiskDecision.REJECTED, 0.0, 0.0, [f"trading_halted:{inp.trading_halt_reason}"])

    if not inp.council_trade_allowed:
        return RiskCheckResult(RiskDecision.REJECTED, 0.0, 0.0, ["council_incomplete_no_new_trades"])

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

    # `max_position_fraction` bounds the MARGIN committed (fraction of equity);
    # notional = margin * leverage, so leverage is a real exposure multiplier
    # (and liquidation a real risk), not a decorative field.
    max_margin = inp.equity * min(inp.dna.risk_profile.max_position_fraction, global_max_position_size)
    if inp.available_margin is not None:
        max_margin = min(max_margin, inp.available_margin)
    max_notional_by_fraction = max_margin * leverage
    from app.core.config import get_settings  # local import keeps this module dependency-light
    max_notional_by_fraction = min(max_notional_by_fraction, inp.equity * get_settings().max_exposure_multiple)
    notional = min(inp.proposed_notional, max_notional_by_fraction)
    if inp.stop_distance_pct is not None and 0 < inp.stop_distance_pct <= 1.0:
        max_by_risk = inp.equity * get_settings().max_loss_per_trade_fraction / inp.stop_distance_pct
        if max_by_risk < notional:
            notional = max_by_risk
            reasons.append("notional_reduced_to_risk_per_trade_limit")
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
