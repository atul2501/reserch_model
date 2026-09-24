"""Worker fencing (spec phase 3): a worker that loses its lease/heartbeat stops trading IMMEDIATELY and cannot
write decisions, orders, positions or balances - even if it only finds out at commit time."""
from __future__ import annotations

import asyncio
import time

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import get_settings
from app.execution.paper_adapter import PaperExecutionAdapter
from app.market.market_data_service import MarketDataService
from app.models.agent import Agent
from app.models.decision import Decision
from app.models.system import WorkerCycle
from app.models.trading import Order, Position
from app.worker import cycle as cycle_mod
from app.worker.lease import LeaseKeeper, LeaseLost, try_acquire
from tests.helpers_market import INTERVAL, T0, FakeHyperliquid, clock_after_bar
from tests.test_council_failclosed import _seed_always_long_population

pytestmark = pytest.mark.usefixtures("immediate_fills")   # position mechanics; see conftest.immediate_fills


@pytest.fixture
def paper(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "council_enabled", False)
    monkeypatch.setattr(s, "paper_latency_ms", 0)
    return s


async def _counts(db):
    return {
        "decisions": (await db.execute(select(func.count()).select_from(Decision))).scalar_one(),
        "orders": (await db.execute(select(func.count()).select_from(Order))).scalar_one(),
        "positions": (await db.execute(select(func.count()).select_from(Position))).scalar_one(),
    }


async def _setup(db, n=6):
    fake = FakeHyperliquid(n_candles=400)
    market = MarketDataService(fake, clock_ms=lambda: clock_after_bar(399))
    await _seed_always_long_population(db, n=n)
    await market.sync_recent_candles(db, lookback_candles=400)
    return market


_OPEN_KEEPERS: list = []


def _keeper(factory, owner, ttl=60.0):
    k = LeaseKeeper(factory, owner_id=owner, ttl_seconds=ttl, heartbeat_seconds=3600)   # heartbeat never fires: the test drives it
    _OPEN_KEEPERS.append(k)
    return k


@pytest.fixture(autouse=True)
async def _close_keepers():
    yield
    for k in _OPEN_KEEPERS:
        if k._task is not None:
            k._task.cancel()
            await asyncio.gather(k._task, return_exceptions=True)
    _OPEN_KEEPERS.clear()


class TakeoverEngine(PaperExecutionAdapter):
    """Paper engine that lets a rival worker take over the lease while the cycle is in flight.

    SQLite is single-writer, so a second connection cannot commit while worker A's transaction is open; the takeover
    is therefore applied inside A's own transaction (as if B's commit had just become visible to A). The real
    cross-connection race is exercised against PostgreSQL in tests/test_postgres_concurrency.py."""

    def __init__(self, db, after_orders: int):
        super().__init__()
        self._db, self._after, self.n = db, after_orders, 0

    async def submit_order(self, request):
        self.n += 1
        if self.n == self._after:
            from sqlalchemy import update
            from app.models.system import WorkerLease

            await self._db.execute(update(WorkerLease).values(owner_id="worker-B", epoch=2, expires_at=time.time() + 60))
        return await super().submit_order(request)


async def test_worker_that_loses_its_lease_mid_cycle_cannot_write_anything(db_engine, db_session, paper):
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    market = await _setup(db_session)
    keeper = _keeper(factory, "worker-A")
    assert await keeper.acquire()
    before = await _counts(db_session)

    engine = TakeoverEngine(db_session, after_orders=2)   # B takes the lease after A already staged some agents
    with pytest.raises(LeaseLost):
        await cycle_mod.run_pending_cycles(db_session, market, None, execution_engine=engine, fence=keeper)

    assert engine.n >= 2, "the takeover must have happened mid-cycle for this test to mean anything"
    assert keeper.is_lost
    await db_session.rollback()
    assert await _counts(db_session) == before                        # not one decision/order/position persisted
    assert (await db_session.execute(select(func.count()).select_from(WorkerCycle))).scalar_one() == 1   # STARTED row only
    row = (await db_session.execute(select(WorkerCycle))).scalar_one()
    assert row.status == "STARTED"                                    # the fenced worker did not even mark it FAILED
    balances = (await db_session.execute(select(Agent.balance))).scalars().all()
    assert set(balances) == {100.0}                                   # no agent balance was touched


async def test_lost_lease_flag_stops_the_cycle_at_the_next_agent(db_engine, db_session, paper):
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    market = await _setup(db_session)
    keeper = _keeper(factory, "worker-A")
    assert await keeper.acquire()

    class LoseAfterFirst(PaperExecutionAdapter):
        n = 0

        async def submit_order(self, request):
            type(self).n += 1
            if type(self).n == 1:
                keeper.lost.set()                                    # what the heartbeat does when it sees a takeover
            return await super().submit_order(request)

    before = await _counts(db_session)
    engine = LoseAfterFirst()
    with pytest.raises(LeaseLost):
        await cycle_mod.run_pending_cycles(db_session, market, None, execution_engine=engine, fence=keeper)
    assert LoseAfterFirst.n == 1                                     # stopped IMMEDIATELY: no second agent was processed
    assert await _counts(db_session) == before


async def test_local_ttl_self_fence_needs_no_database(db_engine):
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    keeper = LeaseKeeper(factory, owner_id="A", ttl_seconds=0.05, heartbeat_seconds=3600)
    assert await keeper.acquire()
    keeper.check_local()                                              # fresh: fine
    await asyncio.sleep(0.08)                                         # cannot renew within the TTL
    with pytest.raises(LeaseLost):
        keeper.check_local()
    assert keeper.is_lost


async def test_worker_that_never_held_the_lease_is_fenced(db_engine, db_session, paper):
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    market = await _setup(db_session, n=2)
    assert await _keeper(factory, "owner").acquire()
    stranger = _keeper(factory, "stranger")                           # never acquired
    with pytest.raises(LeaseLost):
        await cycle_mod.run_pending_cycles(db_session, market, None, execution_engine=PaperExecutionAdapter(), fence=stranger)
    assert (await _counts(db_session))["orders"] == 0


async def test_db_fence_detects_takeover_even_when_local_state_looks_healthy(db_engine, db_session):
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    a = _keeper(factory, "A")
    assert await a.acquire()
    await a.check_db(db_session)                                     # healthy: passes
    await db_session.rollback()                                      # end the read transaction (SQLite is single-writer)
    async with factory() as other:
        await try_acquire(other, "B", 60, now=time.time() + 10_000)
    a.check_local()                                                   # local view has no idea ...
    with pytest.raises(LeaseLost):
        await a.check_db(db_session, lock=True)                       # ... the database fence does
    assert a.is_lost


async def test_heartbeat_marks_the_worker_lost_when_the_database_stays_down_past_the_ttl(db_engine):
    healthy = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    broken = {"on": False}

    def factory():
        if broken["on"]:
            raise ConnectionError("database unreachable")
        return healthy()

    k = LeaseKeeper(factory, owner_id="A", ttl_seconds=0.15, heartbeat_seconds=0.03)
    assert await k.acquire()
    broken["on"] = True
    await asyncio.wait_for(k.lost.wait(), timeout=2)                 # previously: retried forever, never self-fenced
    assert k.is_lost
    await k.close()


# --- idempotency: deterministic ids, released on rollback --------------------------------------------------


async def test_two_workers_on_the_same_candle_produce_one_decision_set(db_engine, db_session, paper):
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    market = await _setup(db_session, n=4)
    a = _keeper(factory, "A")
    assert await a.acquire()
    first = await cycle_mod.run_pending_cycles(db_session, market, None, execution_engine=PaperExecutionAdapter(), fence=a)
    assert first[0].status == "COMPLETED"
    after_a = await _counts(db_session)
    assert after_a["orders"] == 4
    await db_session.rollback()                                      # end the read transaction (SQLite is single-writer)

    # A is replaced by B, who is (wrongly) asked to process the very same candle again.
    await a.close()
    b = _keeper(factory, "B")
    assert await b.acquire()
    row = (await db_session.execute(select(WorkerCycle))).scalar_one()
    row.status, row.completed = "FAILED", False                     # e.g. A crashed right after committing decisions
    await db_session.commit()
    second = await cycle_mod.run_pending_cycles(db_session, market, None, execution_engine=PaperExecutionAdapter(), fence=b)
    assert second[0].status == "COMPLETED"
    assert await _counts(db_session) == after_a                      # nothing decided twice, no duplicate orders


async def test_decision_and_order_ids_are_deterministic_across_retries(db_session, paper):
    from app.agents.decision_loop import decision_id_for
    from app.execution.paper_adapter import new_client_order_id

    market = await _setup(db_session, n=2)
    await cycle_mod.run_pending_cycles(db_session, market, None, execution_engine=PaperExecutionAdapter())
    agent = (await db_session.execute(select(Agent))).scalars().first()
    ot = T0 + 399 * INTERVAL
    d = (await db_session.execute(select(Decision).where(Decision.agent_id == agent.id))).scalar_one()
    assert d.id == decision_id_for(agent.id, ot)
    order = (await db_session.execute(select(Order).where(Order.agent_id == agent.id))).scalar_one()
    assert order.client_order_id == new_client_order_id(str(agent.id), str(d.id))


async def test_a_rolled_back_cycle_retries_without_being_blocked_as_a_duplicate(db_session, paper, monkeypatch):
    """Deterministic order ids + an in-process idempotency guard: a rollback must RELEASE the ids, or the retry of
    the same candle would be refused as 'duplicate_client_order_id' (silently suppressing entries)."""
    market = await _setup(db_session, n=3)
    engine = PaperExecutionAdapter()
    real = cycle_mod.run_decision_cycle
    state = {"n": 0}

    async def commit_fails_once(db, eng, *a, **kw):
        state["n"] += 1
        if state["n"] == 1:
            orig = db.commit

            async def boom():
                await db.rollback()
                raise RuntimeError("commit failed")
            db.commit = boom
            try:
                return await real(db, eng, *a, **kw)
            finally:
                db.commit = orig
        return await real(db, eng, *a, **kw)

    monkeypatch.setattr(cycle_mod, "run_decision_cycle", commit_fails_once)
    first = await cycle_mod.run_pending_cycles(db_session, market, None, execution_engine=engine)
    assert first[0].status == "FAILED"
    assert (await _counts(db_session))["orders"] == 0

    second = await cycle_mod.run_pending_cycles(db_session, market, None, execution_engine=engine)
    assert second[0].status == "COMPLETED"
    assert (await _counts(db_session))["orders"] == 3                # all three agents entered on the retry


async def test_an_agent_savepoint_rollback_releases_its_order_id(db_session, paper, monkeypatch):
    from app.agents import decision_loop as dl

    market = await _setup(db_session, n=2)
    engine = PaperExecutionAdapter()
    real = dl._process_agent
    failed = {"done": False}

    async def fail_once_after_submit(cc, agent):
        await real(cc, agent)
        if not failed["done"]:
            failed["done"] = True
            raise RuntimeError("bookkeeping failed after the fill")   # savepoint rolls the order/position back

    monkeypatch.setattr(dl, "_process_agent", fail_once_after_submit)
    out = await cycle_mod.run_pending_cycles(db_session, market, None, execution_engine=engine)
    assert out[0].status == "COMPLETED" and out[0].agents_processed == 1
    assert (await _counts(db_session))["orders"] == 1

    monkeypatch.setattr(dl, "_process_agent", real)
    row = (await db_session.execute(select(WorkerCycle))).scalar_one()
    row.status, row.completed = "FAILED", False
    await db_session.commit()
    out = await cycle_mod.run_pending_cycles(db_session, market, None, execution_engine=engine)
    assert out[0].status == "COMPLETED"
    assert (await _counts(db_session))["orders"] == 2                # the failed agent's entry was NOT refused as a duplicate
