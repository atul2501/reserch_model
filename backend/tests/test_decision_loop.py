"""Integration test for the per-candle agent decision loop: entry, exit,
and the full audit trail (spec sections 12/18/19/20/32/45)."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.agents.decision_loop import run_decision_cycle
from app.agents.lifecycle import create_generation
from app.execution.paper_adapter import PaperExecutionAdapter
from app.models.agent import Agent
from app.models.decision import Decision
from app.models.enums import RiskDecision, StrategyFamily, StrategyStage
from app.models.strategy import Strategy, StrategyVersion
from app.models.trading import Order, Position, Trade
from app.schemas.market_context import (
    MarketContext,
    MomentumFeatures,
    PriceActionFeatures,
    RegimeState,
    StructureFeatures,
    TrendFeatures,
    VolatilityFeatures,
    VolumeFeatures,
)
from app.schemas.strategy_dna import Condition, PositionSizing, RiskProfile, RuleSet, StrategyDNA

pytestmark = pytest.mark.usefixtures("immediate_fills")   # position mechanics; see conftest.immediate_fills


def _context(open_time: int, close: float, rsi: float, trend_strength: float) -> MarketContext:
    return MarketContext(
        symbol="SOL",
        timeframe="1m",
        candle_open_time=open_time,
        close_price=close,
        is_final=True,
        trend=TrendFeatures(ema_fast=close, ema_slow=close - 1, sma_fast=close, sma_slow=close, ema_slope=0.1, trend_strength=trend_strength),
        momentum=MomentumFeatures(rsi_14=rsi, macd=0.1, macd_signal=0.05, macd_hist=0.05, roc_10=1.0),
        volatility=VolatilityFeatures(atr_14=0.5, realized_vol=0.02, volatility_percentile=0.5, bb_upper=close + 2, bb_middle=close, bb_lower=close - 2, bb_width=0.02),
        structure=StructureFeatures(),
        volume=VolumeFeatures(volume_sma_20=1000, volume_ratio=1.0, volume_spike=False, vwap=close),
        price_action=PriceActionFeatures(body=0.1, wick_ratio=0.1, candle_range=1.0, gap=0.0, is_momentum_candle=False),
        regime=RegimeState(regime="TREND_UP", confidence=0.8),
    )


async def _make_agent(db_session, leverage_limit: float = 1.0, stage: StrategyStage | None = None) -> Agent:
    strategy = Strategy(code=f"STRAT-TEST-{uuid.uuid4().hex[:8]}", family=StrategyFamily.MOMENTUM, name="test")
    db_session.add(strategy)
    await db_session.flush()

    dna = StrategyDNA(
        strategy_family=StrategyFamily.MOMENTUM,
        indicators=[{"name": "rsi", "params": {"period": 14}}],
        entry_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="gt", value=60)]),
        exit_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="lt", value=40)]),
        risk_profile=RiskProfile(max_leverage=leverage_limit, max_position_fraction=0.5),
        position_sizing=PositionSizing(fraction_of_equity=0.1),
        leverage_limit=leverage_limit,
    )
    version_kwargs = {"stage": stage} if stage is not None else {}
    version = StrategyVersion(
        strategy_id=strategy.id, version=1, generation=1, dna=dna.model_dump(mode="json"), **version_kwargs
    )
    db_session.add(version)
    await db_session.flush()

    generation = await create_generation(
        db_session, generation_number=100, strategy_version_ids=[version.id], starting_balance=100.0
    )
    agent = (await db_session.execute(select(Agent).where(Agent.generation == generation.number))).scalar_one()
    return agent


@pytest.mark.asyncio
async def test_entry_signal_opens_position_and_writes_audit_trail(db_session):
    agent = await _make_agent(db_session)
    execution_engine = PaperExecutionAdapter()

    entry_context = _context(open_time=1, close=100.0, rsi=65.0, trend_strength=0.01)
    await run_decision_cycle(
        db_session,
        execution_engine,
        entry_context,
        prev_context=None,
        generation=100,
        council_decision_id=None,
        global_max_leverage=5.0,
        global_max_position_size=0.5,
        global_max_drawdown=0.3,
        global_max_daily_loss=0.1,
        market_data_age_seconds=1.0,
    )

    decisions = (await db_session.execute(select(Decision).where(Decision.agent_id == agent.id))).scalars().all()
    assert len(decisions) == 1
    assert decisions[0].risk_decision == RiskDecision.APPROVED

    orders = (await db_session.execute(select(Order).where(Order.agent_id == agent.id))).scalars().all()
    assert len(orders) == 1

    positions = (await db_session.execute(select(Position).where(Position.agent_id == agent.id))).scalars().all()
    assert len(positions) == 1
    assert positions[0].is_open is True

    await db_session.refresh(agent)
    assert agent.trade_count == 1
    assert agent.balance < 100.0  # entry fee deducted


@pytest.mark.asyncio
async def test_exit_signal_closes_position_and_realizes_pnl(db_session):
    agent = await _make_agent(db_session)
    execution_engine = PaperExecutionAdapter()

    entry_context = _context(open_time=1, close=100.0, rsi=65.0, trend_strength=0.01)
    await run_decision_cycle(
        db_session, execution_engine, entry_context, None, generation=100, council_decision_id=None,
        global_max_leverage=5.0, global_max_position_size=0.5, global_max_drawdown=0.3, global_max_daily_loss=0.1,
        market_data_age_seconds=1.0,
    )

    exit_context = _context(open_time=2, close=110.0, rsi=30.0, trend_strength=0.01)
    await run_decision_cycle(
        db_session, execution_engine, exit_context, entry_context, generation=100, council_decision_id=None,
        global_max_leverage=5.0, global_max_position_size=0.5, global_max_drawdown=0.3, global_max_daily_loss=0.1,
        market_data_age_seconds=1.0,
    )

    positions = (await db_session.execute(select(Position).where(Position.agent_id == agent.id))).scalars().all()
    assert positions[0].is_open is False

    trades = (await db_session.execute(select(Trade).where(Trade.agent_id == agent.id))).scalars().all()
    assert len(trades) == 1
    assert trades[0].net_pnl > 0  # bought at 100, sold at 110

    await db_session.refresh(agent)
    assert agent.realized_pnl > 0
    assert agent.equity > 100.0


@pytest.mark.asyncio
async def test_daily_loss_breaker_rejects_new_entry_after_intraday_loss(db_session):
    agent = await _make_agent(db_session, leverage_limit=3.0)
    execution_engine = PaperExecutionAdapter()

    entry_context = _context(open_time=1, close=100.0, rsi=65.0, trend_strength=0.01)
    await run_decision_cycle(
        db_session, execution_engine, entry_context, None, generation=100, council_decision_id=None,
        global_max_leverage=5.0, global_max_position_size=0.5, global_max_drawdown=0.3, global_max_daily_loss=0.1,
        market_data_age_seconds=1.0,
    )

    # Big same-(UTC-)day loss: the long position exits far below entry.
    exit_context = _context(open_time=2, close=40.0, rsi=30.0, trend_strength=0.01)
    await run_decision_cycle(
        db_session, execution_engine, exit_context, entry_context, generation=100, council_decision_id=None,
        global_max_leverage=5.0, global_max_position_size=0.5, global_max_drawdown=0.3, global_max_daily_loss=0.1,
        market_data_age_seconds=1.0,
    )

    await db_session.refresh(agent)
    assert agent.equity < agent.day_start_equity * 0.9  # more than a 10% same-day loss

    # A fresh entry signal later the same (UTC epoch) day should now be blocked.
    second_entry_context = _context(open_time=3, close=40.0, rsi=65.0, trend_strength=0.01)
    await run_decision_cycle(
        db_session, execution_engine, second_entry_context, exit_context, generation=100, council_decision_id=None,
        global_max_leverage=5.0, global_max_position_size=0.5, global_max_drawdown=0.3, global_max_daily_loss=0.1,
        market_data_age_seconds=1.0,
    )

    decisions = (
        await db_session.execute(
            select(Decision).where(Decision.agent_id == agent.id).order_by(Decision.market_candle_open_time)
        )
    ).scalars().all()
    last_decision = decisions[-1]
    assert last_decision.risk_decision == RiskDecision.REJECTED
    assert "max_daily_loss_exceeded" in last_decision.risk_reasoning["reasons"]

    positions = (await db_session.execute(select(Position).where(Position.agent_id == agent.id))).scalars().all()
    assert len(positions) == 1  # no second position opened — the breaker blocked it


@pytest.mark.asyncio
async def test_daily_loss_breaker_lifts_at_the_next_utc_day_even_without_recovering_equity(db_session):
    """Phase 4.0 characterization gap: the day-rollover reset (day_start_equity,
    day_start_date, daily_trade_count - decision_loop.py's `_process_agent_inner`,
    the `if agent.day_start_date != market_ts.date()` block) is proven for
    daily_trade_count by test_max_trades_per_day_stops_new_entries_and_resets_next_utc_day,
    but nothing previously proved day_start_equity itself resets - the field the
    daily-loss breaker actually reads. Same scenario as
    test_daily_loss_breaker_rejects_new_entry_after_intraday_loss, extended one more
    day: the breaker lifts at UTC rollover even though the agent's equity never
    recovered - because the anchor moved, not because the loss was undone."""
    DAY_MS = 86_400_000
    agent = await _make_agent(db_session, leverage_limit=3.0)
    execution_engine = PaperExecutionAdapter()

    entry_context = _context(open_time=1, close=100.0, rsi=65.0, trend_strength=0.01)
    await run_decision_cycle(
        db_session, execution_engine, entry_context, None, generation=100, council_decision_id=None,
        global_max_leverage=5.0, global_max_position_size=0.5, global_max_drawdown=0.3, global_max_daily_loss=0.1,
        market_data_age_seconds=1.0,
    )
    exit_context = _context(open_time=2, close=40.0, rsi=30.0, trend_strength=0.01)
    await run_decision_cycle(
        db_session, execution_engine, exit_context, entry_context, generation=100, council_decision_id=None,
        global_max_leverage=5.0, global_max_position_size=0.5, global_max_drawdown=0.3, global_max_daily_loss=0.1,
        market_data_age_seconds=1.0,
    )
    await db_session.refresh(agent)
    reduced_equity = agent.equity
    assert reduced_equity < agent.day_start_equity * 0.9   # same-day breaker armed, as in the sibling test

    second_entry_context = _context(open_time=3, close=40.0, rsi=65.0, trend_strength=0.01)
    await run_decision_cycle(
        db_session, execution_engine, second_entry_context, exit_context, generation=100, council_decision_id=None,
        global_max_leverage=5.0, global_max_position_size=0.5, global_max_drawdown=0.3, global_max_daily_loss=0.1,
        market_data_age_seconds=1.0,
    )
    await db_session.refresh(agent)
    assert agent.equity == pytest.approx(reduced_equity)   # still blocked same day: nothing changed

    # Next UTC day. Equity has NOT recovered - reduced_equity is unchanged - but the
    # breaker must lift because day_start_equity re-anchors to the current equity.
    next_day_context = _context(open_time=DAY_MS + 4, close=40.0, rsi=65.0, trend_strength=0.01)
    await run_decision_cycle(
        db_session, execution_engine, next_day_context, second_entry_context, generation=100, council_decision_id=None,
        global_max_leverage=5.0, global_max_position_size=0.5, global_max_drawdown=0.3, global_max_daily_loss=0.1,
        market_data_age_seconds=1.0,
    )
    await db_session.refresh(agent)
    from datetime import datetime, timezone
    assert agent.day_start_date == datetime.fromtimestamp(next_day_context.candle_open_time / 1000, tz=timezone.utc).date()
    assert agent.day_start_equity == pytest.approx(reduced_equity)   # re-anchored to CURRENT equity, not restored

    last_decision = (
        await db_session.execute(
            select(Decision).where(Decision.agent_id == agent.id).order_by(Decision.market_candle_open_time.desc())
        )
    ).scalars().first()
    assert "max_daily_loss_exceeded" not in (last_decision.risk_reasoning or {}).get("reasons", [])
    positions = (await db_session.execute(select(Position).where(Position.agent_id == agent.id))).scalars().all()
    assert len(positions) == 2   # the breaker lifted: a second position was allowed to open


@pytest.mark.asyncio
async def test_duplicate_position_not_opened_while_one_is_active(db_session):
    agent = await _make_agent(db_session)
    execution_engine = PaperExecutionAdapter()

    ctx1 = _context(open_time=1, close=100.0, rsi=65.0, trend_strength=0.01)
    ctx2 = _context(open_time=2, close=101.0, rsi=66.0, trend_strength=0.01)  # still entry-triggering, still open

    for ctx, prev in ((ctx1, None), (ctx2, ctx1)):
        await run_decision_cycle(
            db_session, execution_engine, ctx, prev, generation=100, council_decision_id=None,
            global_max_leverage=5.0, global_max_position_size=0.5, global_max_drawdown=0.3, global_max_daily_loss=0.1,
            market_data_age_seconds=1.0,
        )

    positions = (await db_session.execute(select(Position).where(Position.agent_id == agent.id))).scalars().all()
    assert len(positions) == 1  # no second position opened while one is active


@pytest.mark.asyncio
async def test_second_order_from_the_same_agent_gets_a_distinct_client_order_id(db_session):
    """Live-reproducing regression test: `decision` was constructed but
    never added to the session before the `await db.flush()` meant to
    populate `decision.id` for the idempotency key — so decision.id stayed
    None, and new_client_order_id(agent_id, str(decision.id)) built the
    literal string f"{agent_id}:None" for every entry order. A SECOND
    entry from the same agent (after closing the first position) then
    tried to insert that exact same client_order_id again, violating the
    UNIQUE constraint on Order.client_order_id and crashing the whole
    cycle — this was the confirmed root cause of the live production
    'UNIQUE constraint failed: orders.client_order_id' crash."""
    agent = await _make_agent(db_session)
    execution_engine = PaperExecutionAdapter()

    entry_ctx_1 = _context(open_time=1, close=100.0, rsi=65.0, trend_strength=0.01)
    await run_decision_cycle(
        db_session, execution_engine, entry_ctx_1, None, generation=100, council_decision_id=None,
        global_max_leverage=5.0, global_max_position_size=0.5, global_max_drawdown=0.3, global_max_daily_loss=0.1,
        market_data_age_seconds=1.0,
    )
    exit_ctx = _context(open_time=2, close=110.0, rsi=30.0, trend_strength=0.01)
    await run_decision_cycle(
        db_session, execution_engine, exit_ctx, entry_ctx_1, generation=100, council_decision_id=None,
        global_max_leverage=5.0, global_max_position_size=0.5, global_max_drawdown=0.3, global_max_daily_loss=0.1,
        market_data_age_seconds=1.0,
    )
    entry_ctx_2 = _context(open_time=3, close=100.0, rsi=65.0, trend_strength=0.01)
    # This used to raise sqlalchemy.exc.IntegrityError (UNIQUE constraint
    # failed: orders.client_order_id) — must now succeed cleanly.
    await run_decision_cycle(
        db_session, execution_engine, entry_ctx_2, exit_ctx, generation=100, council_decision_id=None,
        global_max_leverage=5.0, global_max_position_size=0.5, global_max_drawdown=0.3, global_max_daily_loss=0.1,
        market_data_age_seconds=1.0,
    )

    orders = (await db_session.execute(select(Order).where(Order.agent_id == agent.id))).scalars().all()
    # entry, reduce-only exit (exits now go through the ExecutionEngine), entry
    assert len(orders) == 3
    assert sum(1 for o in orders if not o.reduce_only) == 2 and sum(1 for o in orders if o.reduce_only) == 1
    assert len({o.client_order_id for o in orders}) == 3
    assert all("None" not in o.client_order_id for o in orders)


@pytest.mark.asyncio
async def test_closed_trade_is_stamped_with_the_strategy_versions_stage(db_session):
    """Trade.stage must reflect StrategyVersion.stage as it was when the
    trade closed, so stage_metrics_service can isolate a PAPER-stage
    trade's history from a SHADOW-stage one for the same version instead of
    blending them (the reality-gap MVP limitation this column fixes)."""
    agent = await _make_agent(db_session, stage=StrategyStage.PAPER)
    execution_engine = PaperExecutionAdapter()

    entry_context = _context(open_time=1, close=100.0, rsi=65.0, trend_strength=0.01)
    await run_decision_cycle(
        db_session, execution_engine, entry_context, None, generation=100, council_decision_id=None,
        global_max_leverage=5.0, global_max_position_size=0.5, global_max_drawdown=0.3, global_max_daily_loss=0.1,
        market_data_age_seconds=1.0,
    )

    exit_context = _context(open_time=2, close=110.0, rsi=30.0, trend_strength=0.01)
    await run_decision_cycle(
        db_session, execution_engine, exit_context, entry_context, generation=100, council_decision_id=None,
        global_max_leverage=5.0, global_max_position_size=0.5, global_max_drawdown=0.3, global_max_daily_loss=0.1,
        market_data_age_seconds=1.0,
    )

    trades = (await db_session.execute(select(Trade).where(Trade.agent_id == agent.id))).scalars().all()
    assert len(trades) == 1
    assert trades[0].stage == StrategyStage.PAPER


@pytest.mark.asyncio
async def test_one_schema_drifted_strategy_version_does_not_crash_the_whole_cycle(db_session):
    """Root-cause regression test for the reported cycle.unhandled_error:
    run_decision_cycle used to call StrategyDNA.model_validate(v.dna) for
    every StrategyVersion in the generation with zero error handling — one
    StrategyVersion whose stored JSON no longer matches the current
    StrategyDNA schema (schema drift, a hand-edited row, a legacy version)
    raised an uncaught pydantic.ValidationError that crashed the ENTIRE
    decision cycle for every agent in the generation, not just the broken
    one. The fix isolates validation per-version: skip that version's
    agents, keep processing everyone else."""
    strategy_a = Strategy(code=f"STRAT-GOOD-{uuid.uuid4().hex[:6]}", family=StrategyFamily.MOMENTUM, name="good")
    db_session.add(strategy_a)
    await db_session.flush()
    good_dna = StrategyDNA(
        strategy_family=StrategyFamily.MOMENTUM,
        indicators=[{"name": "rsi", "params": {"period": 14}}],
        entry_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="gt", value=60)]),
        exit_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="lt", value=40)]),
        position_sizing=PositionSizing(fraction_of_equity=0.1),
    )
    version_good = StrategyVersion(strategy_id=strategy_a.id, version=1, generation=1, dna=good_dna.model_dump(mode="json"))
    db_session.add(version_good)
    await db_session.flush()

    strategy_b = Strategy(code=f"STRAT-BAD-{uuid.uuid4().hex[:6]}", family=StrategyFamily.MOMENTUM, name="bad")
    db_session.add(strategy_b)
    await db_session.flush()
    bad_dna_json = good_dna.model_dump(mode="json")
    del bad_dna_json["entry_rules"]  # simulate schema drift: a required field missing
    version_bad = StrategyVersion(strategy_id=strategy_b.id, version=1, generation=1, dna=bad_dna_json)
    db_session.add(version_bad)
    await db_session.flush()
    await db_session.commit()

    await create_generation(
        db_session, generation_number=1, strategy_version_ids=[version_good.id, version_bad.id], starting_balance=100.0
    )

    entry_context = _context(open_time=1, close=100.0, rsi=65.0, trend_strength=0.01)
    processed = await run_decision_cycle(
        db_session, PaperExecutionAdapter(), entry_context, None, generation=1, council_decision_id=None,
        global_max_leverage=5.0, global_max_position_size=0.5, global_max_drawdown=0.3, global_max_daily_loss=0.1,
        market_data_age_seconds=1.0,
    )

    # The good agent still got processed despite the other agent's broken
    # DNA — this is what "does not crash the whole cycle" means concretely.
    assert processed == 1
    decisions = (await db_session.execute(select(Decision))).scalars().all()
    assert len(decisions) == 1


@pytest.mark.asyncio
async def test_council_incomplete_blocks_new_entries_but_still_processes_exits(db_session):
    """Fail-closed contract end-to-end: council_trade_allowed=False must
    prevent a NEW position from opening, but an agent that already has a
    position open must still be able to exit (risk-reducing, not
    risk-adding — never blocked)."""
    agent = await _make_agent(db_session)
    execution_engine = PaperExecutionAdapter()

    entry_context = _context(open_time=1, close=100.0, rsi=65.0, trend_strength=0.01)
    await run_decision_cycle(
        db_session, execution_engine, entry_context, None, generation=100, council_decision_id=None,
        global_max_leverage=5.0, global_max_position_size=0.5, global_max_drawdown=0.3, global_max_daily_loss=0.1,
        market_data_age_seconds=1.0, council_trade_allowed=False,
    )
    positions = (await db_session.execute(select(Position).where(Position.agent_id == agent.id))).scalars().all()
    assert len(positions) == 0  # blocked: council incomplete, no new entry
    decisions = (await db_session.execute(select(Decision).where(Decision.agent_id == agent.id))).scalars().all()
    assert decisions[-1].risk_decision == RiskDecision.REJECTED
    assert "council_incomplete_no_new_trades" in decisions[-1].risk_reasoning["reasons"]

    # Now let council recover and open a real position, then verify a
    # later council-incomplete candle still permits closing it.
    confirmed_entry_context = _context(open_time=2, close=100.0, rsi=65.0, trend_strength=0.01)
    await run_decision_cycle(
        db_session, execution_engine, confirmed_entry_context, entry_context, generation=100, council_decision_id=None,
        global_max_leverage=5.0, global_max_position_size=0.5, global_max_drawdown=0.3, global_max_daily_loss=0.1,
        market_data_age_seconds=1.0, council_trade_allowed=True,
    )
    positions = (await db_session.execute(select(Position).where(Position.agent_id == agent.id))).scalars().all()
    assert len(positions) == 1

    exit_context = _context(open_time=3, close=110.0, rsi=30.0, trend_strength=0.01)
    await run_decision_cycle(
        db_session, execution_engine, exit_context, confirmed_entry_context, generation=100, council_decision_id=None,
        global_max_leverage=5.0, global_max_position_size=0.5, global_max_drawdown=0.3, global_max_daily_loss=0.1,
        market_data_age_seconds=1.0, council_trade_allowed=False,  # council incomplete again — exit must still work
    )
    positions = (await db_session.execute(select(Position).where(Position.agent_id == agent.id))).scalars().all()
    assert positions[0].is_open is False
