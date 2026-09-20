"""Professional agent classification (spec section 17). Multiple conditions
must ALL hold — hitting 2x/3x equity alone is never sufficient.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings


@dataclass
class ProfessionalCriteriaInputs:
    trade_count: int
    profit_factor: float | None
    max_drawdown_pct: float
    oos_score: float | None


def is_professional(inputs: ProfessionalCriteriaInputs, settings: Settings) -> tuple[bool, list[str]]:
    """Returns (is_professional, failed_criteria) so the caller/dashboard
    can explain exactly why an agent is or isn't classified professional."""
    failed: list[str] = []

    if inputs.trade_count < settings.pro_min_trades:
        failed.append(f"trade_count {inputs.trade_count} < {settings.pro_min_trades}")

    if inputs.profit_factor is None or inputs.profit_factor < settings.pro_min_profit_factor:
        failed.append(f"profit_factor {inputs.profit_factor} < {settings.pro_min_profit_factor}")

    if inputs.max_drawdown_pct > settings.pro_max_drawdown:
        failed.append(f"max_drawdown {inputs.max_drawdown_pct} > {settings.pro_max_drawdown}")

    if inputs.oos_score is None or inputs.oos_score < settings.pro_min_oos_score:
        failed.append(f"oos_score {inputs.oos_score} < {settings.pro_min_oos_score}")

    return len(failed) == 0, failed
