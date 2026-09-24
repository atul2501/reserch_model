"""Composite fitness engine (spec section 21).

Deliberately NOT raw PnL. Combines return, risk, consistency, robustness,
and out-of-sample performance into one score, with configurable weights.
The formula below is a reasonable starting point, not a claimed optimum —
the evolution engine's own research loop is expected to challenge it.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FitnessInputs:
    net_return_pct: float          # e.g. 0.35 for +35%
    profit_factor: float | None    # gross_win / gross_loss
    max_drawdown_pct: float        # 0.0-1.0
    expectancy: float | None       # average net PnL per trade, in account-currency terms
    trade_count: int
    win_rate: float | None         # 0.0-1.0
    survival_days: float
    sharpe_like: float | None
    oos_score: float | None        # 0.0-1.0, out-of-sample performance ratio
    walk_forward_score: float | None  # 0.0-1.0, consistency across walk-forward windows
    return_volatility: float | None   # stddev of periodic returns, for instability penalty
    # 0.0-1.0, this agent's mean composite_correlation to its peers this
    # generation (StrategyCorrelationEngine). Optional and only ever
    # applied when FitnessWeights.correlation_penalty_weight > 0 — the
    # locked-in rule is that correlation is a breeding-time diversity
    # signal, never a kill signal, so this stays an opt-in soft term.
    mean_pairwise_correlation: float | None = None
    # --- v2 inputs (all optional: a missing input contributes 0, never a guess) ---
    # Score of the VALIDATION slice (out-of-sample w.r.t. training). The protected
    # FINAL OOS slice never appears here — it only gates promotion.
    regime_robustness: float | None = None      # 0..1 from RegimeValidation classification
    adversarial_robustness: float | None = None # 0..1 from the adversarial suite
    profit_factor_score_input: float | None = None
    starting_balance: float = 100.0
    daily_consistency: float | None = None      # fraction of profitable days, 0..1
    dead: bool = False                          # the agent died (survival_days must then be time-to-death)


@dataclass
class FitnessWeights:
    return_weight: float = 1.0
    risk_weight: float = 1.0
    consistency_weight: float = 1.0
    robustness_weight: float = 1.0
    oos_weight: float = 1.5
    drawdown_penalty_weight: float = 2.0
    instability_penalty_weight: float = 1.0
    # Defaults to 0.0 (off): correlation must never lower an agent's
    # fitness ranking by default, per the locked-in "diversity signal, not
    # a kill/rank signal" rule — set explicitly nonzero to opt in.
    correlation_penalty_weight: float = 0.0
    # v2 terms (0 contribution when the input is missing)
    expectancy_weight: float = 0.5
    regime_weight: float = 1.0
    adversarial_weight: float = 1.0
    # Doing nothing is not a strategy: the less trading evidence an agent has, the larger this penalty (0 at full
    # confidence). A dead agent additionally pays `death_penalty_weight`.
    inactivity_penalty_weight: float = 0.25
    death_penalty_weight: float = 1.0

    @classmethod
    def from_settings(cls, settings=None) -> "FitnessWeights":
        """Weights are configuration, not code: FITNESS_W_* environment variables."""
        from app.core.config import get_settings
        s = settings or get_settings()
        return cls(
            return_weight=s.fitness_w_return, risk_weight=s.fitness_w_risk, consistency_weight=s.fitness_w_consistency,
            robustness_weight=s.fitness_w_robustness, oos_weight=s.fitness_w_oos,
            drawdown_penalty_weight=s.fitness_w_drawdown, instability_penalty_weight=s.fitness_w_instability,
            correlation_penalty_weight=s.fitness_w_correlation, expectancy_weight=s.fitness_w_expectancy,
            regime_weight=s.fitness_w_regime, adversarial_weight=s.fitness_w_adversarial,
            inactivity_penalty_weight=s.fitness_w_inactivity, death_penalty_weight=s.fitness_w_death,
        )

    def as_dict(self) -> dict[str, float]:
        return self.__dict__.copy()


@dataclass
class FitnessResult:
    fitness: float
    return_score: float
    risk_score: float
    consistency_score: float
    robustness_score: float
    oos_score: float
    drawdown_penalty: float
    instability_penalty: float
    correlation_penalty: float = 0.0
    expectancy_score: float = 0.0
    regime_score: float = 0.0
    adversarial_score: float = 0.0
    inactivity_penalty: float = 0.0
    death_penalty: float = 0.0
    weights_used: dict[str, float] = field(default_factory=dict)


MIN_TRADES_FOR_FULL_CONFIDENCE = 30
PROFIT_FACTOR_CAP = 3.0   # mirrors app.analytics.performance_metrics_engine.PROFIT_FACTOR_CAP


def _profit_factor_component(inputs: FitnessInputs) -> float:
    """[-1, 1]. Explicit, never an `x or default` fallback (zero is a real, bad, value):
       no trades            -> 0     (no evidence either way)
       profit factor 0.0    -> -1    (only losses)
       None with wins       -> cap   (no losing trade => infinite profit factor, capped)
       None without wins    -> 0     (only flat trades)"""
    if inputs.trade_count <= 0:
        return 0.0
    pf = inputs.profit_factor
    if pf is None:
        pf = PROFIT_FACTOR_CAP if (inputs.win_rate or 0.0) > 0 else 1.0
    pf = min(pf, PROFIT_FACTOR_CAP)
    return _clip(pf - 1.0, lo=-1.0, hi=1.0)


def _win_rate_component(inputs: FitnessInputs) -> float:
    """[-1, 1]. A 0% win rate over real trades is the WORST score (-1), not neutral; no trades/unknown is 0."""
    if inputs.trade_count <= 0 or inputs.win_rate is None:
        return 0.0
    return _clip(inputs.win_rate - 0.5, lo=-0.5, hi=0.5) * 2


def compute_fitness(inputs: FitnessInputs, weights: FitnessWeights | None = None) -> FitnessResult:
    w = weights or FitnessWeights()

    # Sample-size confidence multiplier: an agent with 3 trades should not
    # outrank one with 300 just because its tiny sample got lucky.
    sample_confidence = min(1.0, inputs.trade_count / MIN_TRADES_FOR_FULL_CONFIDENCE)

    return_score = _clip(inputs.net_return_pct) * sample_confidence

    profit_factor_component = _profit_factor_component(inputs)
    win_rate_component = _win_rate_component(inputs)
    risk_score = ((profit_factor_component + win_rate_component) / 2) * sample_confidence

    consistency_score = (inputs.walk_forward_score or 0.0) * sample_confidence

    # Survival only counts as evidence when the agent actually traded: sitting idle for 30 days proves nothing.
    survival_component = _clip(inputs.survival_days / 30.0, lo=0.0, hi=1.0) * sample_confidence
    sharpe_component = _clip((inputs.sharpe_like or 0.0) / 2.0, lo=-1.0, hi=1.0)
    robustness_score = (survival_component + sharpe_component) / 2

    oos_score = inputs.oos_score if inputs.oos_score is not None else 0.0

    drawdown_penalty = inputs.max_drawdown_pct  # 0..1, higher drawdown = bigger penalty
    instability_penalty = _clip(inputs.return_volatility or 0.0, lo=0.0, hi=1.0)
    # 0.0 whenever correlation_penalty_weight is left at its default (0.0)
    # or no correlation data was supplied — see FitnessWeights' docstring.
    correlation_penalty = _clip(inputs.mean_pairwise_correlation or 0.0, lo=0.0, hi=1.0)

    # v2 components — each bounded to [-1, 1] / [0, 1] so no single metric can
    # dominate the composite, and each is 0 when its input is unavailable.
    expectancy_score = 0.0
    if inputs.expectancy is not None and inputs.starting_balance > 0:
        # +0.5% of the starting balance per trade is "full marks".
        expectancy_score = _clip(inputs.expectancy / (0.005 * inputs.starting_balance)) * sample_confidence
    regime_score = _clip(inputs.regime_robustness or 0.0, lo=0.0, hi=1.0)
    adversarial_score = _clip(inputs.adversarial_robustness or 0.0, lo=0.0, hi=1.0)

    inactivity_penalty = 1.0 - sample_confidence
    death_penalty = 1.0 if inputs.dead else 0.0

    fitness = (
        w.expectancy_weight * expectancy_score
        + w.regime_weight * regime_score
        + w.adversarial_weight * adversarial_score
        + w.return_weight * return_score
        + w.risk_weight * risk_score
        + w.consistency_weight * consistency_score
        + w.robustness_weight * robustness_score
        + w.oos_weight * oos_score
        - w.drawdown_penalty_weight * drawdown_penalty
        - w.instability_penalty_weight * instability_penalty
        - w.correlation_penalty_weight * correlation_penalty
        - w.inactivity_penalty_weight * inactivity_penalty
        - w.death_penalty_weight * death_penalty
    )

    return FitnessResult(
        fitness=fitness,
        return_score=return_score,
        risk_score=risk_score,
        consistency_score=consistency_score,
        robustness_score=robustness_score,
        oos_score=oos_score,
        drawdown_penalty=drawdown_penalty,
        instability_penalty=instability_penalty,
        correlation_penalty=correlation_penalty,
        expectancy_score=expectancy_score,
        regime_score=regime_score,
        adversarial_score=adversarial_score,
        inactivity_penalty=inactivity_penalty,
        death_penalty=death_penalty,
        weights_used=w.as_dict(),
    )


def _clip(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))
