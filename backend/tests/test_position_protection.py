"""Open positions never lose protection (spec phases 9, 24) and books always reconcile (phase 8)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.agents import decision_loop as dl
from app.core.config import get_settings
from app.execution import accounting
from app.execution.base import ExecutionResult
from app.execution.paper_adapter import PaperExecutionAdapter
from app.market.market_data_service import MarketDataService
from app.models.agent import Agent
from app.models.enums import AgentStatus, OrderStatus, Side
from app.models.market import MarketCandle
from app.models.strategy import StrategyVersion
from app.models.trading import Order, Position, Trade
from app.worker import cycle as cycle_mod
from tests.helpers_agents import MINUTE, T0, cycle, make_agents, make_context, make_dna
from tests.helpers_market import INTERVAL, T0 as MT0, FakeHyperliquid, clock_after_bar
from tests.test_council_failclosed import _seed_always_long_population


async def open_position(db, agent, *, entry=100.0, qty=1.0, stop=99.0, tp=None, leverage=1.0, side=Side.LONG,
                        last_processed=None, trail=None):
    """A hand-made open position (as if opened on an earlier bar)."""
    p = Position(
        agent_id=agent.id, symbol="SOL", side=side, quantity=qty, entry_price=entry, leverage=leverage,
        initial_margin=entry * qty / leverage, peak_price=entry, trough_price=entry, stop_loss_price=stop,
        take_profit_price=tp, trailing_stop_distance=trail, entry_fee=0.0, is_open=True,
        opened_at=datetime.fromtimestamp((T0 - MINUTE) / 1000, tz=timezone.utc),
        last_funding_time=datetime.fromtimestamp((T0 - MINUTE) / 1000, tz=timezone.utc),
        last_processed_open_time=last_processed,
    )
    db.add(p)
    await db.commit()
    return p


CRASH = dict(open_=100.0, high=100.2, low=90.0)     # a bar that trades through a 99 stop


# --- sweep: every open position is protected whatever happened to its agent -------------------------------


async def test_a_failing_agent_still_gets_its_position_stopped_by_the_sweep(db_session, monkeypatch):
    (agent,) = await make_agents(db_session, [make_dna()])
    pos = await open_position(db_session, agent)

    async def boom(cc, a):
        raise RuntimeError("agent processing exploded")

    monkeypatch.setattr(dl, "_process_agent_inner", boom)
    await cycle(db_session, PaperExecutionAdapter(), make_context(1, 95.0, **CRASH, rsi=50.0))
    await db_session.refresh(pos)
    assert pos.is_open is False
    (trade,) = (await db_session.execute(select(Trade))).scalars().all()
    assert trade.exit_reason == "stop_loss"


async def test_a_position_from_a_different_generation_than_the_one_being_cycled_is_still_protected(db_session):
    """Phase 4.0 characterization gap: protect_open_positions's own docstring names
    'other generation' as one of the sweep's four target cases (failed agent, invalid
    DNA, DEAD/orphan owner, other generation) - the other three are covered by this
    file's other tests, but nothing previously exercised this one directly. The
    sweep queries ALL open positions with no generation filter; run_decision_cycle's
    per-agent loop only ever processes the ONE generation it's called with (100,
    cycle()'s default here) - a position belonging to an agent in a different,
    never-cycled generation must still be swept."""
    (other_gen_agent,) = await make_agents(db_session, [make_dna()], generation=99)
    pos = await open_position(db_session, other_gen_agent, stop=99.0)
    assert pos.last_processed_open_time is None

    # generation=100 (cycle()'s default) has ZERO agents - the per-agent loop does
    # nothing at all; only the mandatory sweep can reach this position.
    ctx1 = make_context(1, 100.0, rsi=50.0)
    await cycle(db_session, PaperExecutionAdapter(), ctx1)
    await db_session.refresh(pos)
    assert pos.last_processed_open_time == ctx1.candle_open_time
    assert pos.is_open is True   # not stopped this bar - this just proves the sweep reached it

    await cycle(db_session, PaperExecutionAdapter(), make_context(2, 95.0, **CRASH, rsi=50.0))
    await db_session.refresh(pos)
    assert pos.is_open is False   # the sweep closed it via the stop, exactly as it would within generation=100
    (trade,) = (await db_session.execute(select(Trade))).scalars().all()
    assert trade.agent_id == other_gen_agent.id and trade.exit_reason == "stop_loss"


async def _invalid_dna_agents(db, n):
    """Agents whose stored DNA no longer validates (schema drift). DNA is immutable in the DB, so create them that way."""
    import uuid
    from app.agents.lifecycle import create_generation
    from app.models.enums import StrategyFamily
    from app.models.strategy import Strategy

    ids = []
    for _ in range(n):
        strat = Strategy(code=f"S-{uuid.uuid4().hex[:8]}", family=StrategyFamily.MOMENTUM, name="drifted")
        db.add(strat)
        await db.flush()
        v = StrategyVersion(strategy_id=strat.id, version=1, generation=1, dna={"not": "a valid dna"})
        db.add(v)
        await db.flush()
        ids.append(v.id)
    await create_generation(db, generation_number=100, strategy_version_ids=ids, starting_balance=100.0)
    return list((await db.execute(select(Agent).where(Agent.generation == 100).order_by(Agent.identifier))).scalars().all())


async def test_an_agent_with_invalid_dna_still_gets_protection_and_is_parked(db_session):
    a1, a2 = await _invalid_dna_agents(db_session, 2)
    pos = await open_position(db_session, a1)
    await cycle(db_session, PaperExecutionAdapter(), make_context(1, 95.0, **CRASH, rsi=50.0))
    await db_session.refresh(pos)
    await db_session.refresh(a1)
    await db_session.refresh(a2)
    assert pos.is_open is False                                   # protected through the fallback (stored levels)
    assert a2.status == AgentStatus.PAUSED                        # flat + untradeable DNA => no zombie ACTIVE agent
    assert a1.status == AgentStatus.ACTIVE                        # held a position this cycle; parked on the next one
    await cycle(db_session, PaperExecutionAdapter(), make_context(2, 95.0, rsi=50.0))
    await db_session.refresh(a1)
    assert a1.status == AgentStatus.PAUSED


async def test_a_dead_agents_orphan_position_is_resolved_deterministically(db_session):
    (agent,) = await make_agents(db_session, [make_dna()])
    pos = await open_position(db_session, agent, stop=None)     # no protective level: only the orphan rule can close it
    agent.status, agent.death_reason, agent.equity, agent.final_equity = AgentStatus.DEAD, "equity_depleted", 5.0, 5.0
    await db_session.commit()
    await cycle(db_session, PaperExecutionAdapter(), make_context(1, 100.0, rsi=50.0))
    await db_session.refresh(pos)
    await db_session.refresh(agent)
    assert pos.is_open is False
    (trade,) = (await db_session.execute(select(Trade))).scalars().all()
    assert trade.exit_reason == "agent_death"
    assert agent.status == AgentStatus.DEAD and agent.final_equity == pytest.approx(agent.balance)   # refrozen after exit costs
    assert agent.equity == pytest.approx(agent.balance)


class FailingExits(PaperExecutionAdapter):
    async def submit_order(self, request):
        self._track(request.agent_id, request.client_order_id)
        return ExecutionResult(request.client_order_id, OrderStatus.FAILED, None, 0.0, 0.0, 0.0, 0, {},
                               rejection_reason="no_liquidity")


async def test_an_exit_that_keeps_failing_is_force_settled_so_no_agent_is_stuck(db_session):
    (agent,) = await make_agents(db_session, [make_dna()])
    pos = await open_position(db_session, agent, stop=None)
    agent.status = AgentStatus.DEAD
    await db_session.commit()
    eng = FailingExits()
    for i in (1, 2):
        await cycle(db_session, eng, make_context(i, 100.0, rsi=50.0))
        await db_session.refresh(pos)
        assert pos.is_open and pos.exit_attempts == i                 # retried every bar, still open
    await cycle(db_session, eng, make_context(3, 100.0, rsi=50.0))
    await db_session.refresh(pos)
    assert pos.is_open is False
    (trade,) = (await db_session.execute(select(Trade))).scalars().all()
    assert "force_settled" in trade.exit_reason


async def test_protection_is_idempotent_per_bar(db_session):
    (agent,) = await make_agents(db_session, [make_dna()])
    pos = await open_position(db_session, agent, stop=None, trail=None)
    ctx = make_context(1, 101.0, open_=100.0, high=105.0, low=99.5, rsi=50.0)
    eng = PaperExecutionAdapter()
    assert await dl.protect_open_positions(db_session, eng, ctx) == 1
    await db_session.refresh(pos)
    assert pos.peak_price == 105.0 and pos.last_processed_open_time == ctx.candle_open_time
    assert await dl.protect_open_positions(db_session, eng, ctx) == 0    # the same bar is never evaluated twice
    with pytest.raises(Exception):
        await dl.protect_open_positions(db_session, eng, ctx.model_copy(update={"is_final": False}))


async def test_trailing_state_survives_a_restart(db_engine, db_session):
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from app.schemas.strategy_dna import TrailingStopConfig

    (agent,) = await make_agents(db_session, [make_dna(trailing_stop=TrailingStopConfig(enabled=True, activation_pct=0.0, trail_pct=1.0))])
    pos = await open_position(db_session, agent, stop=None, trail=1.0)
    pid = pos.id
    await cycle(db_session, PaperExecutionAdapter(), make_context(1, 104.0, open_=100.0, high=106.0, low=99.9, rsi=50.0))
    fresh = async_sessionmaker(bind=db_engine, expire_on_commit=False)          # a "restarted" worker: brand-new session
    async with fresh() as s2:
        again = await s2.get(Position, pid)
        assert again.peak_price == 106.0 and again.is_open
        assert again.last_processed_open_time == T0 + MINUTE


async def test_a_flat_agent_that_can_never_afford_an_order_is_retired_as_dead(db_session):
    (agent,) = await make_agents(db_session, [make_dna()], balance=100.0)
    agent.balance = agent.equity = 0.5
    await db_session.commit()
    await cycle(db_session, PaperExecutionAdapter(), make_context(1, 100.0, rsi=50.0))
    await db_session.refresh(agent)
    assert agent.status == AgentStatus.DEAD and agent.death_reason == "untradeable_equity"


# --- bad debt: equity/PnL stay reconcilable through a gap past liquidation -------------------------------


async def test_gap_through_liquidation_records_bad_debt_and_the_books_reconcile(db_session):
    (agent,) = await make_agents(db_session, [make_dna()], balance=100.0)
    pos = await open_position(db_session, agent, entry=100.0, qty=10.0, stop=None, leverage=10.0)   # $1000 on $100
    await cycle(db_session, PaperExecutionAdapter(), make_context(1, 50.0, open_=50.0, high=50.5, low=49.0, rsi=50.0))
    await db_session.refresh(agent)
    (trade,) = (await db_session.execute(select(Trade))).scalars().all()
    assert trade.exit_reason == "liquidation"
    assert trade.gross_pnl == pytest.approx(-500.0, rel=0.01)          # ~-$500 on a $100 account
    assert agent.balance == 0.0                                         # never negative ...
    assert agent.bad_debt == pytest.approx(trade.bad_debt) and agent.bad_debt > 390.0   # ... but the shortfall is recorded
    assert accounting.reconcile(starting_balance=agent.starting_balance, balance=agent.balance,
                                realized_pnl=agent.realized_pnl, bad_debt=agent.bad_debt) == pytest.approx(0.0, abs=1e-6)
    assert agent.status == AgentStatus.DEAD and agent.final_equity == 0.0


async def test_books_reconcile_after_many_round_trips(db_session):
    (agent,) = await make_agents(db_session, [make_dna()], balance=100.0)
    eng = PaperExecutionAdapter()
    i = 1
    for _ in range(4):
        await cycle(db_session, eng, make_context(i, 100.0, rsi=65.0)); i += 1          # signal
        await cycle(db_session, eng, make_context(i, 100.5, open_=100.2, high=100.8, low=100.1, rsi=50.0)); i += 1   # fill
        await cycle(db_session, eng, make_context(i, 100.4, open_=100.5, high=100.7, low=100.2, rsi=30.0)); i += 1   # exit signal
        await cycle(db_session, eng, make_context(i, 101.0, open_=100.6, high=101.1, low=100.4, rsi=50.0)); i += 1   # exit fills
    await db_session.refresh(agent)
    trades = (await db_session.execute(select(Trade))).scalars().all()
    assert len(trades) == 4 and not (await db_session.execute(select(Position).where(Position.is_open.is_(True)))).first()
    assert accounting.reconcile(starting_balance=100.0, balance=agent.balance, realized_pnl=agent.realized_pnl,
                                bad_debt=agent.bad_debt) == pytest.approx(0.0, abs=1e-9)
    assert agent.realized_pnl == pytest.approx(sum(t.net_pnl for t in trades))
    assert agent.fees_paid == pytest.approx(sum(t.fees for t in trades))


async def test_reconciles_with_an_open_position_and_funding(db_session):
    from app.models.market import FundingRate

    (agent,) = await make_agents(db_session, [make_dna()], balance=100.0)
    pos = await open_position(db_session, agent, entry=100.0, qty=2.0, stop=None)
    pos.entry_fee = 0.3
    agent.balance -= 0.3
    db_session.add(FundingRate(symbol="SOL", time_ms=T0 + 30_000, rate=0.0005))
    await db_session.commit()
    await cycle(db_session, PaperExecutionAdapter(), make_context(1, 100.0, rsi=50.0))
    await db_session.refresh(agent)
    await db_session.refresh(pos)
    assert pos.funding_accrued == pytest.approx(2.0 * 100.0 * 0.0005) and pos.is_open
    assert accounting.reconcile(starting_balance=100.0, balance=agent.balance, realized_pnl=agent.realized_pnl,
                                bad_debt=agent.bad_debt, open_entry_fee=pos.entry_fee, open_funding=pos.funding_accrued) == pytest.approx(0.0, abs=1e-9)


# --- worker paths: failed attempt / poison candle / skipped catch-up bars --------------------------------


async def _positions_at(db, fake, bar):
    market = MarketDataService(fake, clock_ms=lambda: clock_after_bar(bar))
    await _seed_always_long_population(db, n=3)
    await market.sync_recent_candles(db, lookback_candles=400)
    out = await cycle_mod.run_pending_cycles(db, market, None, execution_engine=PaperExecutionAdapter())
    assert out[0].status == "COMPLETED"
    ps = (await db.execute(select(Position).where(Position.is_open.is_(True)))).scalars().all()
    assert len(ps) == 3
    return ps


def _crash_bar(fake, i):
    c = dict(fake.candles[i])
    c.update(o="90.0", h="90.5", l="40.0", c="41.0")
    fake.candles[i] = c


@pytest.fixture
def paper(monkeypatch, immediate_fills):
    s = get_settings()
    monkeypatch.setattr(s, "council_enabled", False)
    monkeypatch.setattr(s, "paper_latency_ms", 0)
    return s


async def test_positions_are_protected_when_the_decision_phase_fails_and_when_the_bar_becomes_poison(db_session, paper, monkeypatch):
    fake = FakeHyperliquid(n_candles=400)
    ps = await _positions_at(db_session, fake, 396)
    _crash_bar(fake, 397)
    market = MarketDataService(fake, clock_ms=lambda: clock_after_bar(397))

    async def always_fail(*a, **k):
        raise RuntimeError("decision phase exploded")

    monkeypatch.setattr(cycle_mod, "run_decision_cycle", always_fail)
    out = await cycle_mod.run_pending_cycles(db_session, market, None, execution_engine=PaperExecutionAdapter())
    assert out[0].status == "FAILED"
    for p in ps:
        await db_session.refresh(p)
    assert all(not p.is_open for p in ps)                                   # protected even though the decision failed
    assert len((await db_session.execute(select(Trade))).scalars().all()) == 3
    # keep failing until the bar is abandoned: nothing may blow up and nothing is double-processed
    for _ in range(cycle_mod.MAX_CYCLE_ATTEMPTS + 1):
        await cycle_mod.run_pending_cycles(db_session, market, None, execution_engine=PaperExecutionAdapter())
    assert len((await db_session.execute(select(Trade))).scalars().all()) == 3


async def test_skipped_catchup_bars_still_protect_open_positions(db_session, paper, monkeypatch):
    fake = FakeHyperliquid(n_candles=400)
    ps = await _positions_at(db_session, fake, 390)
    _crash_bar(fake, 393)                                                    # inside the window that will be skipped
    monkeypatch.setattr(paper, "max_catchup_bars", 2)
    market = MarketDataService(fake, clock_ms=lambda: clock_after_bar(399))
    out = await cycle_mod.run_pending_cycles(db_session, market, None, execution_engine=PaperExecutionAdapter())
    assert [o.candle_open_time for o in out] == [MT0 + 398 * INTERVAL, MT0 + 399 * INTERVAL]
    for p in ps:
        await db_session.refresh(p)
    assert all(not p.is_open for p in ps)                                    # closed by the protective replay of bar 393
    trades = (await db_session.execute(select(Trade))).scalars().all()
    assert len(trades) == 3 and {t.exit_reason for t in trades} <= {"stop_loss", "liquidation"}
    assert all(t.closed_at.timestamp() * 1000 <= MT0 + 394 * INTERVAL for t in trades)   # ... on the crash bar, not later
