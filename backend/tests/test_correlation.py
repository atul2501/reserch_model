"""StrategyCorrelationEngine: DNA-structural similarity, behavioral
correlation from real Trade/Position data, persistence, and the
diversity-pressure signal generator that must never touch Agent.status."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.analytics.fitness_engine import FitnessInputs, FitnessWeights, compute_fitness
from app.evolution.correlation import entry_condition_similarity, exit_condition_similarity, feature_similarity
from app.evolution.correlation_service import (
    GenerationCorrelationReport,
    PairCorrelation,
    apply_diversity_pressure,
    compute_generation_correlation_report,
    persist_generation_correlation,
)
from app.models.agent import Agent
from app.models.correlation import AgentCorrelation, CorrelationConvergenceSnapshot
from app.models.enums import AgentStatus, Side, StrategyFamily
from app.models.strategy import Strategy, StrategyVersion
from app.models.trading import Trade
from app.schemas.strategy_dna import Condition, RuleSet, StrategyDNA


def _dna(*, family=StrategyFamily.MOMENTUM, indicator_name="rsi", entry_value=60, exit_value=40) -> StrategyDNA:
    return StrategyDNA(
        strategy_family=family,
        indicators=[{"name": indicator_name, "params": {"period": 14}}],
        entry_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="gt", value=entry_value)]),
        exit_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="lt", value=exit_value)]),
    )


def test_feature_similarity_identical_dna_is_1():
    dna = _dna()
    assert feature_similarity(dna, dna) == pytest.approx(1.0)


def test_feature_similarity_zero_overlap_is_0():
    a = _dna(indicator_name="rsi")
    b = _dna(indicator_name="macd")
    assert feature_similarity(a, b) == pytest.approx(0.0)


def test_entry_condition_similarity_identical_is_1():
    dna = _dna()
    assert entry_condition_similarity(dna, dna) == pytest.approx(1.0)


def test_entry_condition_similarity_different_thresholds_is_partial():
    a = _dna(entry_value=60)
    b = _dna(entry_value=90)
    sim = entry_condition_similarity(a, b)
    assert 0.0 <= sim < 1.0  # same logic, different condition tuple -> partial credit from the logic-match term


def test_exit_condition_similarity_identical_is_1():
    dna = _dna()
    assert exit_condition_similarity(dna, dna) == pytest.approx(1.0)


async def _seed_agent(db_session, *, generation: int, family: StrategyFamily, dna: StrategyDNA | None = None) -> Agent:
    dna = dna or _dna(family=family)
    code = f"STRAT-TEST-{uuid.uuid4().hex[:8]}"
    strategy = Strategy(code=code, family=family, name=code)
    db_session.add(strategy)
    await db_session.flush()
    version = StrategyVersion(strategy_id=strategy.id, version=1, generation=generation, dna=dna.model_dump(mode="json"))
    db_session.add(version)
    await db_session.flush()

    agent = Agent(
        identifier=f"GEN{generation:02d}-AG{uuid.uuid4().hex[:6]}",
        generation=generation,
        strategy_version_id=version.id,
        starting_balance=100.0,
        balance=100.0,
        equity=100.0,
        peak_equity=100.0,
        day_start_equity=100.0,
        day_start_date=date.today(),
    )
    db_session.add(agent)
    await db_session.flush()
    return agent


async def _add_trade(db_session, agent: Agent, *, side: Side, net_pnl: float, closed_at: datetime, holding_minutes: int = 5):
    db_session.add(
        Trade(
            agent_id=agent.id, position_id=uuid.uuid4(), symbol="SOL", side=side, quantity=1.0,
            entry_price=100.0, exit_price=100.0 + net_pnl, gross_pnl=net_pnl, fees=0.0, net_pnl=net_pnl,
            opened_at=closed_at - timedelta(minutes=holding_minutes), closed_at=closed_at,
            holding_seconds=holding_minutes * 60, exit_reason="signal",
        )
    )


@pytest.mark.asyncio
async def test_two_agents_trading_identically_have_high_composite_correlation(db_session):
    """Pearson correlation is undefined (NaN, filtered to None) when a
    series has zero variance, so the direction/return signal needs to
    actually vary bucket-to-bucket — both agents alternate LONG/SHORT in
    lockstep with matching PnL sign here, giving a well-defined, strongly
    positive correlation."""
    generation = 300
    dna = _dna()
    agent_a = await _seed_agent(db_session, generation=generation, family=StrategyFamily.MOMENTUM, dna=dna)
    agent_b = await _seed_agent(db_session, generation=generation, family=StrategyFamily.MOMENTUM, dna=dna)

    now = datetime.now(timezone.utc)
    pattern = [(Side.LONG, 3.0), (Side.SHORT, -1.0), (Side.LONG, 2.0), (Side.SHORT, -2.0), (Side.LONG, 4.0), (Side.SHORT, -1.5)]
    for i, (side, pnl) in enumerate(pattern):
        closed = now - timedelta(hours=len(pattern) - i)
        await _add_trade(db_session, agent_a, side=side, net_pnl=pnl, closed_at=closed)
        await _add_trade(db_session, agent_b, side=side, net_pnl=pnl, closed_at=closed)
    await db_session.commit()

    report = await compute_generation_correlation_report(db_session, generation=generation, lookback_days=30)

    assert len(report.pairs) == 1
    pair = report.pairs[0]
    assert pair.dna_similarity == pytest.approx(1.0)  # identical DNA
    assert pair.trade_direction_correlation == pytest.approx(1.0)
    assert pair.return_correlation == pytest.approx(1.0)
    assert pair.composite_correlation > 0.8


@pytest.mark.asyncio
async def test_two_agents_trading_oppositely_have_low_direction_correlation(db_session):
    generation = 301
    agent_a = await _seed_agent(db_session, generation=generation, family=StrategyFamily.MOMENTUM)
    agent_b = await _seed_agent(db_session, generation=generation, family=StrategyFamily.MEAN_REVERSION)

    now = datetime.now(timezone.utc)
    pattern_a = [(Side.LONG, 1.0), (Side.SHORT, -1.0), (Side.LONG, 1.0), (Side.SHORT, -1.0), (Side.LONG, 1.0), (Side.SHORT, -1.0)]
    pattern_b = [(Side.SHORT, -1.0), (Side.LONG, 1.0), (Side.SHORT, -1.0), (Side.LONG, 1.0), (Side.SHORT, -1.0), (Side.LONG, 1.0)]
    for i in range(len(pattern_a)):
        closed = now - timedelta(hours=len(pattern_a) - i)
        await _add_trade(db_session, agent_a, side=pattern_a[i][0], net_pnl=pattern_a[i][1], closed_at=closed)
        await _add_trade(db_session, agent_b, side=pattern_b[i][0], net_pnl=pattern_b[i][1], closed_at=closed)
    await db_session.commit()

    report = await compute_generation_correlation_report(db_session, generation=generation, lookback_days=30)

    pair = report.pairs[0]
    assert pair.trade_direction_correlation == pytest.approx(-1.0)  # exactly inverted every bucket
    assert pair.dna_similarity < 1.0  # different family


@pytest.mark.asyncio
async def test_persist_generation_correlation_never_overwrites(db_session):
    generation = 302
    await _seed_agent(db_session, generation=generation, family=StrategyFamily.MOMENTUM)
    await _seed_agent(db_session, generation=generation, family=StrategyFamily.MOMENTUM)
    await db_session.commit()

    report = await compute_generation_correlation_report(db_session, generation=generation)
    await persist_generation_correlation(db_session, report)
    await db_session.commit()
    await persist_generation_correlation(db_session, report)
    await db_session.commit()

    rows = (
        await db_session.execute(select(AgentCorrelation).where(AgentCorrelation.generation == generation))
    ).scalars().all()
    assert len(rows) == 2  # 1 pair x 2 persist calls, not deduplicated/overwritten


@pytest.mark.asyncio
async def test_apply_diversity_pressure_flags_high_correlation_and_never_touches_agent_status(db_session):
    generation = 303
    report = GenerationCorrelationReport(
        generation=generation,
        pairs=[],
        population_diversity_score=0.05,  # well below the floor
        mean_pairwise_correlation=0.95,   # well above max_strategy_correlation
        pct_agents_above_max_correlation=0.9,
        family_distribution={"momentum": 8, "breakout": 2},
    )

    action = await apply_diversity_pressure(
        db_session, report=report, max_strategy_correlation=0.80, min_strategy_diversity=0.60
    )
    await db_session.commit()

    assert action.diversity_pressure_applied is True
    assert action.mutation_rate_multiplier > 1.0
    assert "breakout" in action.preserve_family_codes  # minority family preserved
    assert action.reasons

    snapshot = (
        await db_session.execute(
            select(CorrelationConvergenceSnapshot).where(CorrelationConvergenceSnapshot.generation == generation)
        )
    ).scalar_one()
    assert snapshot.diversity_pressure_applied is True

    # The hard rule: correlation must never kill an agent. Assert no agent
    # anywhere in the test DB was set to DEAD by this call.
    dead_agents = (await db_session.execute(select(Agent).where(Agent.status == AgentStatus.DEAD))).scalars().all()
    assert dead_agents == []


@pytest.mark.asyncio
async def test_apply_diversity_pressure_no_pressure_when_healthy(db_session):
    report = GenerationCorrelationReport(
        generation=304,
        pairs=[],
        population_diversity_score=0.90,
        mean_pairwise_correlation=0.10,
        pct_agents_above_max_correlation=0.0,
        family_distribution={"momentum": 5, "breakout": 5},
    )
    action = await apply_diversity_pressure(
        db_session, report=report, max_strategy_correlation=0.80, min_strategy_diversity=0.60
    )
    await db_session.commit()

    assert action.diversity_pressure_applied is False
    assert action.mutation_rate_multiplier == pytest.approx(1.0)
    assert action.families_to_inject == []


def test_correlation_penalty_weight_defaults_to_zero_and_never_lowers_fitness():
    inputs_without_correlation = FitnessInputs(
        net_return_pct=0.10, profit_factor=1.5, max_drawdown_pct=0.05, expectancy=1.0,
        trade_count=50, win_rate=0.6, survival_days=30, sharpe_like=1.0,
        oos_score=0.8, walk_forward_score=0.8, return_volatility=0.1,
    )
    inputs_with_high_correlation = FitnessInputs(
        net_return_pct=0.10, profit_factor=1.5, max_drawdown_pct=0.05, expectancy=1.0,
        trade_count=50, win_rate=0.6, survival_days=30, sharpe_like=1.0,
        oos_score=0.8, walk_forward_score=0.8, return_volatility=0.1,
        mean_pairwise_correlation=0.99,
    )
    result_without = compute_fitness(inputs_without_correlation)
    result_with = compute_fitness(inputs_with_high_correlation)
    assert result_without.fitness == pytest.approx(result_with.fitness)  # default weight is 0.0 -> no effect
