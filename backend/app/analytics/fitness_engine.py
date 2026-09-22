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
    weights_used: dict[str, float] = field(default_factory=dict)


MIN_TRADES_FOR_FULL_CONFIDENCE = 30


def compute_fitness(inputs: FitnessInputs, weights: FitnessWeights | None = None) -> FitnessResult:
    w = weights or FitnessWeights()

    # Sample-size confidence multiplier: an agent with 3 trades should not
    # outrank one with 300 just because its tiny sample got lucky.
    sample_confidence = min(1.0, inputs.trade_count / MIN_TRADES_FOR_FULL_CONFIDENCE)

    return_score = _clip(inputs.net_return_pct) * sample_confidence

    profit_factor_component = _clip((inputs.profit_factor or 1.0) - 1.0, lo=-1.0, hi=1.0)
    win_rate_component = _clip((inputs.win_rate or 0.5) - 0.5, lo=-0.5, hi=0.5) * 2
    risk_score = ((profit_factor_component + win_rate_component) / 2) * sample_confidence

    consistency_score = (inputs.walk_forward_score or 0.0) * sample_confidence

    survival_component = _clip(inputs.survival_days / 30.0, lo=0.0, hi=1.0)
    sharpe_component = _clip((inputs.sharpe_like or 0.0) / 2.0, lo=-1.0, hi=1.0)
    robustness_score = (survival_component + sharpe_component) / 2

    oos_score = inputs.oos_score if inputs.oos_score is not None else 0.0

    drawdown_penalty = inputs.max_drawdown_pct  # 0..1, higher drawdown = bigger penalty
    instability_penalty = _clip(inputs.return_volatility or 0.0, lo=0.0, hi=1.0)
    # 0.0 whenever correlation_penalty_weight is left at its default (0.0)
    # or no correlation data was supplied — see FitnessWeights' docstring.
    correlation_penalty = _clip(inputs.mean_pairwise_correlation or 0.0, lo=0.0, hi=1.0)

    fitness = (
        w.return_weight * return_score
        + w.risk_weight * risk_score
        + w.consistency_weight * consistency_score
        + w.robustness_weight * robustness_score
        + w.oos_weight * oos_score
        - w.drawdown_penalty_weight * drawdown_penalty
        - w.instability_penalty_weight * instability_penalty
        - w.correlation_penalty_weight * correlation_penalty
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
        weights_used=w.as_dict(),
    )


def _clip(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))
