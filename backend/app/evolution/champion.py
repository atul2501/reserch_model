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
    # --- robustness / evidence gates (phase 27). A None input is MISSING
    # EVIDENCE and blocks promotion: nothing is promoted on PnL alone. ---
    min_adversarial_robustness: float = 0.5
    # Regime classification is EVIDENCE, not a veto: specialists (and even FRAGILE/UNSTABLE
    # strategies) are never rejected outright, but FRAGILE/UNSTABLE must show a clearer
    # out-of-sample edge (higher OOS bar). `blocked_regime_classes` is empty by default.
    blocked_regime_classes: tuple[str, ...] = ()
    regime_penalty_classes: tuple[str, ...] = ("FRAGILE", "UNSTABLE")
    regime_penalty_oos_margin: float = 0.10
    max_strategy_correlation: float = 0.85
    max_reality_gap_return_degradation: float = 0.35   # paper return may not fall >35% below backtest
    min_paper_trade_count: int = 30
    min_observation_days: int = 14

    @classmethod
    def from_settings(cls, settings=None) -> "PromotionCriteria":
        from app.core.config import get_settings
        s = settings or get_settings()
        return cls(
            min_trade_count=s.champion_min_trade_count, min_oos_score=s.champion_min_oos_score,
            min_walk_forward_consistency=s.champion_min_walk_forward_consistency, max_drawdown=s.champion_max_drawdown,
            min_profit_factor=s.champion_min_profit_factor, min_fitness_improvement=s.champion_min_fitness_improvement,
            min_adversarial_robustness=s.champion_min_adversarial_robustness,
            max_strategy_correlation=s.max_strategy_correlation,
            max_reality_gap_return_degradation=s.reality_gap_max_acceptable_degradation_pct,
            min_paper_trade_count=s.champion_min_paper_trade_count, min_observation_days=s.champion_min_observation_days,
        )


@dataclass
class CandidateMetrics:
    trade_count: int
    oos_score: float | None
    walk_forward_consistency: float | None
    max_drawdown: float
    profit_factor: float | None
    fitness: float
    adversarial_robustness: float | None = None
    regime_classification: str | None = None
    mean_correlation: float | None = None
    reality_gap_return_degradation: float | None = None   # +x = paper return is x below backtest
    paper_trade_count: int | None = None


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
    required_oos = criteria.min_oos_score + (
        criteria.regime_penalty_oos_margin if challenger.regime_classification in criteria.regime_penalty_classes else 0.0
    )
    if (challenger.oos_score or 0.0) < required_oos:
        reasons.append(f"oos_score {challenger.oos_score} < required {required_oos:.2f}")
    if (challenger.walk_forward_consistency or 0.0) < criteria.min_walk_forward_consistency:
        reasons.append(
            f"walk_forward_consistency {challenger.walk_forward_consistency} < required {criteria.min_walk_forward_consistency}"
        )
    if challenger.max_drawdown > criteria.max_drawdown:
        reasons.append(f"max_drawdown {challenger.max_drawdown} > allowed {criteria.max_drawdown}")
    if (challenger.profit_factor or 0.0) < criteria.min_profit_factor:
        reasons.append(f"profit_factor {challenger.profit_factor} < required {criteria.min_profit_factor}")

    # --- robustness / evidence gates ------------------------------------------------
    if challenger.adversarial_robustness is None:
        reasons.append("missing_evidence: adversarial robustness not evaluated")
    elif challenger.adversarial_robustness < criteria.min_adversarial_robustness:
        reasons.append(f"adversarial_robustness {challenger.adversarial_robustness:.2f} < required {criteria.min_adversarial_robustness}")
    if challenger.regime_classification is None:
        reasons.append("missing_evidence: regime validation not evaluated")
    elif challenger.regime_classification in criteria.blocked_regime_classes:
        reasons.append(f"regime_classification {challenger.regime_classification} is blocked")
    if challenger.mean_correlation is not None and challenger.mean_correlation > criteria.max_strategy_correlation:
        reasons.append(f"mean_correlation {challenger.mean_correlation:.2f} > allowed {criteria.max_strategy_correlation}")
    if challenger.reality_gap_return_degradation is None:
        reasons.append("missing_evidence: reality gap (backtest -> paper) not measurable")
    elif challenger.reality_gap_return_degradation > criteria.max_reality_gap_return_degradation:
        reasons.append(
            f"reality_gap_return_degradation {challenger.reality_gap_return_degradation:.2f} > allowed {criteria.max_reality_gap_return_degradation}"
        )
    if (challenger.paper_trade_count or 0) < criteria.min_paper_trade_count:
        reasons.append(f"paper_trade_count {challenger.paper_trade_count or 0} < required {criteria.min_paper_trade_count}")

    if champion is not None:
        improvement = challenger.fitness - champion.fitness
        if improvement < criteria.min_fitness_improvement:
            reasons.append(
                f"fitness improvement {improvement:.4f} < required margin {criteria.min_fitness_improvement}"
            )

    return PromotionDecision(promote=len(reasons) == 0, reasons=reasons)
