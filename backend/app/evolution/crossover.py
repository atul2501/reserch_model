"""DNA crossover (spec section 25): combine two successful parents' DNA
into one child. Uses the fitter parent's strategy_family/rules and blends
scalar risk/sizing parameters — keeps the result independently valid."""
from __future__ import annotations

import random

from app.schemas.strategy_dna import StrategyDNA


def crossover(parent_a: StrategyDNA, parent_b: StrategyDNA, rng: random.Random | None = None) -> StrategyDNA:
    rng = rng or random.Random()
    a, b = parent_a.model_dump(), parent_b.model_dump()

    child = dict(a if rng.random() < 0.5 else b)  # base structure (family, rules, indicators) from one parent

    child["risk_profile"] = {
        "max_leverage": rng.choice([a["risk_profile"]["max_leverage"], b["risk_profile"]["max_leverage"]]),
        "max_position_fraction": _blend(a["risk_profile"]["max_position_fraction"], b["risk_profile"]["max_position_fraction"], rng),
        "max_daily_loss_fraction": _blend(a["risk_profile"]["max_daily_loss_fraction"], b["risk_profile"]["max_daily_loss_fraction"], rng),
        "max_drawdown_fraction": _blend(a["risk_profile"]["max_drawdown_fraction"], b["risk_profile"]["max_drawdown_fraction"], rng),
    }
    child["position_sizing"] = dict(rng.choice([a["position_sizing"], b["position_sizing"]]))
    child["stop_loss"] = dict(rng.choice([a["stop_loss"], b["stop_loss"]]))
    child["take_profit"] = dict(rng.choice([a["take_profit"], b["take_profit"]]))
    child["trailing_stop"] = dict(rng.choice([a["trailing_stop"], b["trailing_stop"]]))
    child["cooldown"] = dict(rng.choice([a["cooldown"], b["cooldown"]]))
    child["max_trades_per_day"] = rng.choice([a["max_trades_per_day"], b["max_trades_per_day"]])
    child["leverage_limit"] = min(child["risk_profile"]["max_leverage"], rng.choice([a["leverage_limit"], b["leverage_limit"]]))

    return StrategyDNA.model_validate(child)


def _blend(x: float, y: float, rng: random.Random) -> float:
    t = rng.random()
    return round(x * t + y * (1 - t), 4)
