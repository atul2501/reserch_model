"""Composite fitness (spec phase 30): not raw PnL, bounded, configurable,
correlation is soft pressure, specialists keep value, final OOS excluded."""
from __future__ import annotations

import pytest

from app.analytics.fitness_engine import FitnessInputs, FitnessWeights, compute_fitness


def base(**kw):
    d = dict(net_return_pct=0.1, profit_factor=1.5, max_drawdown_pct=0.05, expectancy=0.4, trade_count=60, win_rate=0.55,
             survival_days=10.0, sharpe_like=0.5, oos_score=0.5, walk_forward_score=0.6, return_volatility=0.02,
             starting_balance=100.0)
    d.update(kw)
    return FitnessInputs(**d)


def test_fitness_is_not_raw_pnl_a_high_return_with_ruinous_drawdown_can_lose():
    safe = compute_fitness(base(net_return_pct=0.10, max_drawdown_pct=0.05))
    reckless = compute_fitness(base(net_return_pct=0.60, max_drawdown_pct=0.60, walk_forward_score=0.1, oos_score=0.0))
    assert safe.fitness > reckless.fitness


def test_every_component_is_bounded_so_one_metric_cannot_dominate():
    huge = compute_fitness(base(net_return_pct=50.0, expectancy=1e6, profit_factor=1e6, sharpe_like=1e6,
                                regime_robustness=5.0, adversarial_robustness=5.0))
    assert abs(huge.return_score) <= 1.0 and abs(huge.expectancy_score) <= 1.0 and 0 <= huge.regime_score <= 1.0
    assert 0 <= huge.adversarial_score <= 1.0 and abs(huge.risk_score) <= 1.0
    assert huge.fitness < 12   # bounded above by the sum of the (bounded) weighted components


def test_small_samples_are_discounted():
    few = compute_fitness(base(trade_count=3))
    many = compute_fitness(base(trade_count=90))
    assert few.return_score < many.return_score and few.expectancy_score < many.expectancy_score


def test_missing_evidence_contributes_nothing_it_is_never_guessed():
    r = compute_fitness(base(oos_score=None, walk_forward_score=None, regime_robustness=None, adversarial_robustness=None, expectancy=None))
    assert (r.oos_score, r.consistency_score, r.regime_score, r.adversarial_score, r.expectancy_score) == (0, 0, 0, 0, 0)


def test_regime_specialists_are_valued_not_discarded():
    from app.analytics.fitness_service import REGIME_CLASS_SCORE
    assert REGIME_CLASS_SCORE["ROBUST"] > REGIME_CLASS_SCORE["REGIME_SPECIALIST"] > REGIME_CLASS_SCORE["FRAGILE"] > REGIME_CLASS_SCORE["UNSTABLE"] > 0
    spec = compute_fitness(base(regime_robustness=REGIME_CLASS_SCORE["REGIME_SPECIALIST"]))
    frag = compute_fitness(base(regime_robustness=REGIME_CLASS_SCORE["FRAGILE"]))
    assert spec.fitness > frag.fitness


def test_correlation_is_a_soft_penalty_and_never_a_kill():
    w = FitnessWeights(correlation_penalty_weight=0.3)
    lone = compute_fitness(base(mean_pairwise_correlation=0.1), w)
    clone = compute_fitness(base(mean_pairwise_correlation=0.95), w)
    assert lone.fitness > clone.fitness
    assert clone.fitness > 0 or clone.fitness == pytest.approx(lone.fitness - 0.3 * 0.85)   # lowered, bounded, still a number
    assert compute_fitness(base(mean_pairwise_correlation=0.95)).correlation_penalty == pytest.approx(0.95)


def test_weights_are_configurable_from_settings(monkeypatch):
    from app.core.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "fitness_w_oos", 4.0)
    monkeypatch.setattr(s, "fitness_w_drawdown", 0.0)
    w = FitnessWeights.from_settings(s)
    assert w.oos_weight == 4.0 and w.drawdown_penalty_weight == 0.0
    assert compute_fitness(base(oos_score=1.0), w).fitness > compute_fitness(base(oos_score=0.0), w).fitness


def test_survival_and_consistency_reward_longevity():
    old = compute_fitness(base(survival_days=40, walk_forward_score=0.9))
    young = compute_fitness(base(survival_days=1, walk_forward_score=0.1))
    assert old.fitness > young.fitness


def test_consistency_score_uses_daily_consistency_when_walk_forward_is_unavailable():
    """BUG: FitnessInputs.daily_consistency is computed and passed by every caller
    (fitness_service, fitness_forward) but compute_fitness never reads it -
    consistency_score depended on walk_forward_score alone, which is unavailable
    for most agents (no WALK_FORWARD-stage metrics yet in their generation)."""
    r = compute_fitness(base(walk_forward_score=None, daily_consistency=0.8, trade_count=90))
    assert r.consistency_score == pytest.approx(0.8)


def test_consistency_score_blends_walk_forward_and_daily_when_both_available():
    r = compute_fitness(base(walk_forward_score=0.4, daily_consistency=0.8, trade_count=90))
    assert r.consistency_score == pytest.approx(0.6)   # mean of the two available signals


def test_consistency_score_is_still_zero_when_both_signals_are_missing():
    r = compute_fitness(base(walk_forward_score=None, daily_consistency=None, trade_count=90))
    assert r.consistency_score == 0.0


async def test_service_never_reads_the_final_oos_stage_metrics(db_session):
    """The protected OUT_OF_SAMPLE score must not influence selection fitness."""
    import uuid
    from datetime import datetime, timezone
    from app.analytics.fitness_service import compute_and_persist_agent_fitness
    from app.models.enums import StrategyStage
    from app.models.stage_metrics import StageMetrics
    from tests.helpers_agents import make_agents
    from tests.test_backtest_parity import ema_cross_dna
    (agent,) = await make_agents(db_session, [ema_cross_dna(5, 20)])
    now = datetime.now(timezone.utc)
    for stage, score in ((StrategyStage.BACKTEST, 0.2), (StrategyStage.OUT_OF_SAMPLE, 0.99)):
        db_session.add(StageMetrics(strategy_version_id=agent.strategy_version_id, stage=stage, net_return_pct=0.1,
                                    max_drawdown_pct=0.05, trade_count=50, oos_score=score, computed_at=now))
    await db_session.commit()
    await compute_and_persist_agent_fitness(db_session, generation=100)
    from app.models.metrics import FitnessScore
    from sqlalchemy import select
    fs = (await db_session.execute(select(FitnessScore).where(FitnessScore.agent_id == agent.id))).scalar_one()
    assert fs.oos_score == pytest.approx(0.2)        # validation-slice score from BACKTEST, not 0.99 from the lockbox
