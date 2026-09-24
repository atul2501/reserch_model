"""Fitness edge cases (spec phase 17): zero is a real value, idleness is not rewarded, survival ends at death."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.analytics.fitness_engine import FitnessInputs, FitnessWeights, compute_fitness
from app.analytics.performance_metrics_engine import PROFIT_FACTOR_CAP, capped_profit_factor
from app.models.enums import AgentStatus
from tests.helpers_agents import make_agents, make_dna


def inp(**kw):
    base = dict(net_return_pct=0.0, profit_factor=None, max_drawdown_pct=0.0, expectancy=None, trade_count=0, win_rate=None,
                survival_days=10.0, sharpe_like=None, oos_score=None, walk_forward_score=None, return_volatility=None)
    base.update(kw)
    return FitnessInputs(**base)


W = FitnessWeights()


def test_zero_profit_factor_is_the_worst_score_not_neutral():
    losing = compute_fitness(inp(trade_count=40, profit_factor=0.0, win_rate=0.0), W)
    neutral = compute_fitness(inp(trade_count=40, profit_factor=1.0, win_rate=0.5), W)
    assert losing.risk_score == pytest.approx(-1.0)          # previously `0.0 or 1.0` => 0 (neutral)
    assert neutral.risk_score == pytest.approx(0.0)
    assert losing.fitness < neutral.fitness


def test_zero_win_rate_is_negative_not_neutral():
    assert compute_fitness(inp(trade_count=40, profit_factor=0.5, win_rate=0.0), W).risk_score < \
           compute_fitness(inp(trade_count=40, profit_factor=0.5, win_rate=0.5), W).risk_score


def test_no_losing_trade_is_a_capped_infinite_profit_factor_not_neutral():
    all_wins = compute_fitness(inp(trade_count=40, profit_factor=None, win_rate=1.0), W)
    assert all_wins.risk_score == pytest.approx(1.0)         # (cap-1 clipped to 1 + win-rate 1) / 2
    huge = compute_fitness(inp(trade_count=40, profit_factor=1e9, win_rate=1.0), W)
    assert huge.risk_score == pytest.approx(all_wins.risk_score)     # a huge PF cannot dominate
    assert capped_profit_factor(10.0, 0.0) == PROFIT_FACTOR_CAP and capped_profit_factor(0.0, 0.0) is None
    assert capped_profit_factor(10.0, 5.0) == 2.0


def test_no_trades_means_no_evidence_not_a_good_score():
    r = compute_fitness(inp(trade_count=0, profit_factor=None, win_rate=None), W)
    assert r.risk_score == 0.0 and r.return_score == 0.0 and r.consistency_score == 0.0


def test_an_idle_agent_earns_no_survival_credit_and_is_penalised():
    idle = compute_fitness(inp(trade_count=0, survival_days=30.0), W)
    active = compute_fitness(inp(trade_count=30, survival_days=30.0, profit_factor=1.0, win_rate=0.5), W)
    assert idle.robustness_score == pytest.approx(0.0)       # 30 idle days prove nothing (was +0.5)
    assert idle.inactivity_penalty == pytest.approx(1.0) and active.inactivity_penalty == 0.0
    assert idle.fitness < 0                                 # idleness is below break-even, never a free ride
    assert idle.fitness < active.fitness


def test_small_samples_are_discounted_smoothly():
    a = compute_fitness(inp(trade_count=3, net_return_pct=0.5, profit_factor=3.0, win_rate=1.0), W)
    b = compute_fitness(inp(trade_count=30, net_return_pct=0.5, profit_factor=3.0, win_rate=1.0), W)
    assert a.return_score < b.return_score and a.inactivity_penalty > b.inactivity_penalty and a.fitness < b.fitness


def test_a_dead_agent_pays_a_death_penalty():
    alive = compute_fitness(inp(trade_count=30, profit_factor=1.5, win_rate=0.6, dead=False), W)
    dead = compute_fitness(inp(trade_count=30, profit_factor=1.5, win_rate=0.6, dead=True), W)
    assert dead.death_penalty == 1.0 and dead.fitness == pytest.approx(alive.fitness - W.death_penalty_weight)


async def test_survival_is_measured_to_the_actual_death_time(db_session):
    from app.analytics.performance_metrics_service import compute_agent_performance_metric

    (agent,) = await make_agents(db_session, [make_dna()])
    born = agent.created_at
    agent.status = AgentStatus.DEAD
    agent.death_timestamp = born + timedelta(days=2)
    await db_session.commit()
    later = born + timedelta(days=10)
    metric = await compute_agent_performance_metric(db_session, agent, as_of=later)
    assert metric.survival_seconds == pytest.approx(2 * 86400, rel=1e-6)      # NOT 10 days: the agent stopped living
    agent.death_timestamp = None
    agent.status = AgentStatus.ACTIVE
    alive = await compute_agent_performance_metric(db_session, agent, as_of=later)
    assert alive.survival_seconds == pytest.approx(10 * 86400, rel=1e-6)


async def test_fitness_service_flags_dead_agents(db_session):
    from app.analytics.fitness_service import compute_and_persist_agent_fitness
    from app.models.agent import Agent

    a1, a2 = await make_agents(db_session, [make_dna(), make_dna()], generation=100)
    a2.status, a2.death_timestamp = AgentStatus.DEAD, a2.created_at + timedelta(hours=1)
    await db_session.commit()
    await compute_and_persist_agent_fitness(db_session, generation=100)
    await db_session.commit()
    rows = {a.id: a.fitness for a in (await db_session.execute(select(Agent))).scalars().all()}
    assert rows[a2.id] < rows[a1.id]


def test_all_winning_backtest_stores_a_capped_profit_factor_not_none():
    from app.backtesting.engine import BacktestResult, BacktestTrade
    from app.backtesting.stage_metrics_service import persist_backtest_metrics
    from app.models.enums import Side, StrategyStage
    import uuid

    trades = [BacktestTrade(Side.LONG, 1, 2, 100, 101, 1, 1.0, "signal", fee=0.1) for _ in range(3)]
    res = BacktestResult(equity_curve=[100, 103], trades=trades, final_equity=103.0, starting_equity=100.0)
    row = persist_backtest_metrics(uuid.uuid4(), StrategyStage.BACKTEST, res)
    assert row.profit_factor == PROFIT_FACTOR_CAP     # None would fail the promotion gate's profit-factor check
