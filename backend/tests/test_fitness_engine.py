"""Fitness must not reduce to raw PnL (spec section 21/49/45)."""
from __future__ import annotations

from app.analytics.fitness_engine import FitnessInputs, compute_fitness


def test_high_pnl_high_drawdown_scores_lower_than_moderate_pnl_low_drawdown():
    risky = FitnessInputs(
        net_return_pct=5.0,  # +500%
        profit_factor=1.2,
        max_drawdown_pct=0.5,
        expectancy=10.0,
        trade_count=100,
        win_rate=0.4,
        survival_days=30,
        sharpe_like=0.3,
        oos_score=0.3,
        walk_forward_score=0.2,
        return_volatility=0.6,
    )
    disciplined = FitnessInputs(
        net_return_pct=3.0,  # +300%
        profit_factor=1.8,
        max_drawdown_pct=0.1,
        expectancy=8.0,
        trade_count=100,
        win_rate=0.55,
        survival_days=30,
        sharpe_like=1.2,
        oos_score=0.8,
        walk_forward_score=0.75,
        return_volatility=0.15,
    )
    risky_fitness = compute_fitness(risky).fitness
    disciplined_fitness = compute_fitness(disciplined).fitness
    assert disciplined_fitness > risky_fitness


def test_low_trade_count_is_discounted_by_sample_confidence():
    lucky_few_trades = FitnessInputs(
        net_return_pct=2.0,
        profit_factor=5.0,
        max_drawdown_pct=0.05,
        expectancy=20.0,
        trade_count=2,
        win_rate=1.0,
        survival_days=5,
        sharpe_like=2.0,
        oos_score=None,
        walk_forward_score=None,
        return_volatility=0.1,
    )
    proven_track_record = FitnessInputs(
        net_return_pct=0.8,
        profit_factor=1.6,
        max_drawdown_pct=0.15,
        expectancy=3.0,
        trade_count=200,
        win_rate=0.55,
        survival_days=60,
        sharpe_like=1.0,
        oos_score=0.7,
        walk_forward_score=0.65,
        return_volatility=0.2,
    )
    assert compute_fitness(proven_track_record).fitness > compute_fitness(lucky_few_trades).fitness
