"""Champion/challenger promotion logic (spec section 28).

A challenger can NEVER replace the champion purely for having made more
money over a short window. Promotion requires clearing every configured
validation gate. Every promotion/rejection is recorded by the caller via
EvolutionEvent (spec section 25).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PromotionCriteria:
    min_trade_count: int = 100
    min_oos_score: float = 0.65
    min_walk_forward_consistency: float = 0.6
    max_drawdown: float = 0.25
    min_profit_factor: float = 1.3
    # Challenger must beat champion's fitness by at least this margin —
    # prevents flip-flopping on noise.
    min_fitness_improvement: float = 0.05


@dataclass
class CandidateMetrics:
    trade_count: int
    oos_score: float | None
    walk_forward_consistency: float | None
    max_drawdown: float
    profit_factor: float | None
    fitness: float


@dataclass
class PromotionDecision:
    promote: bool
    reasons: list[str]


def evaluate_promotion(
    challenger: CandidateMetrics,
    champion: CandidateMetrics | None,
    criteria: PromotionCriteria,
) -> PromotionDecision:
    reasons: list[str] = []

    if challenger.trade_count < criteria.min_trade_count:
        reasons.append(f"trade_count {challenger.trade_count} < required {criteria.min_trade_count}")
    if (challenger.oos_score or 0.0) < criteria.min_oos_score:
        reasons.append(f"oos_score {challenger.oos_score} < required {criteria.min_oos_score}")
    if (challenger.walk_forward_consistency or 0.0) < criteria.min_walk_forward_consistency:
        reasons.append(
            f"walk_forward_consistency {challenger.walk_forward_consistency} < required {criteria.min_walk_forward_consistency}"
        )
    if challenger.max_drawdown > criteria.max_drawdown:
        reasons.append(f"max_drawdown {challenger.max_drawdown} > allowed {criteria.max_drawdown}")
    if (challenger.profit_factor or 0.0) < criteria.min_profit_factor:
        reasons.append(f"profit_factor {challenger.profit_factor} < required {criteria.min_profit_factor}")

    if champion is not None:
        improvement = challenger.fitness - champion.fitness
        if improvement < criteria.min_fitness_improvement:
            reasons.append(
                f"fitness improvement {improvement:.4f} < required margin {criteria.min_fitness_improvement}"
            )

    return PromotionDecision(promote=len(reasons) == 0, reasons=reasons)
