"""Routes backtest/adversarial position sizing through the real
`risk.risk_engine.check_trade` instead of reimplementing its rules a second
time — `run_backtest` has no real `Agent` DB row, so this adapts the Agent
fields `check_trade` actually reads (`peak_equity`, `equity`,
`starting_balance`) into a minimal duck-typed stand-in rather than
constructing a full ORM row.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.models.enums import Side
from app.models.enums import RiskDecision
from app.risk.risk_engine import RiskCheckInput, check_trade
from app.schemas.strategy_dna import StrategyDNA


@dataclass
class _SyntheticAgentState:
    peak_equity: float
    starting_balance: float
    equity: float


def backtest_risk_check(
    *,
    dna: StrategyDNA,
    side: Side,
    proposed_notional: float,
    proposed_leverage: float,
    current_price: float,
    atr: float,
    equity: float,
    peak_equity: float,
    starting_equity: float,
    day_start_equity: float,
    global_max_leverage: float,
    global_max_position_size: float,
    global_max_drawdown: float,
    global_max_daily_loss: float,
    stop_distance_pct: float | None = None,
) -> float:
    """Returns the risk-approved notional (0.0 if the real Risk Engine would
    reject this entry) for one proposed backtest entry. Never bypassed:
    every entry `run_backtest` takes when `enforce_risk_engine=True` goes
    through this — the exact same `check_trade` the live/paper loop uses."""
    synthetic_agent = _SyntheticAgentState(peak_equity=peak_equity, starting_balance=starting_equity, equity=equity)
    result = check_trade(
        RiskCheckInput(
            agent=synthetic_agent,  # type: ignore[arg-type]  # duck-typed: only .peak_equity/.equity/.starting_balance are read
            dna=dna,
            side=side,
            proposed_notional=proposed_notional,
            proposed_leverage=proposed_leverage,
            current_price=current_price,
            atr=atr,
            equity=equity,
            daily_pnl=equity - day_start_equity,
            has_open_position=False,
            market_data_age_seconds=None,
            stop_distance_pct=stop_distance_pct,
        ),
        global_max_leverage=global_max_leverage,
        global_max_position_size=global_max_position_size,
        global_max_drawdown=global_max_drawdown,
        global_max_daily_loss=global_max_daily_loss,
    )
    if result.decision == RiskDecision.REJECTED:
        return 0.0
    return result.approved_notional
