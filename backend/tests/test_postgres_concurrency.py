"""REAL PostgreSQL behaviour (spec phase 25): true multi-connection races, the lease fence, the driver's actual bind-
parameter limit, PG-native triggers/constraints, pool exhaustion and session timeouts.

Skips (like tests/test_postgres.py) when no server answers on TEST_POSTGRES_ADMIN_URL; CI runs it against a Postgres 16
service, so these are not decoration."""
from __future__ import annotations

import asyncio
import time
import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, TimeoutError as PoolTimeout
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

asyncpg = pytest.importorskip("asyncpg")
from tests.test_postgres import _alembic, pg_database  # noqa: E402,F401  (fixture re-export)


@pytest.fixture
async def pg(pg_database):
    assert _alembic(pg_database, "upgrade", "head").returncode == 0
    engine = create_async_engine(pg_database, pool_size=12, max_overflow=0)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    yield factory, engine, pg_database
    await engine.dispose()


# --- lease: real concurrent connections ---------------------------------------------------------------------------------


async def test_concurrent_lease_acquire_has_exactly_one_winner_on_postgres(pg):
    from app.worker.lease import try_acquire

    factory, _, _ = pg

    async def attempt(owner):
        async with factory() as s:
            return await try_acquire(s, owner, 60)

    results = await asyncio.gather(*(attempt(f"w{i}") for i in range(10)))
    assert sum(r.acquired for r in results) == 1
    assert {r.epoch for r in results} == {1}


async def test_lease_expiry_is_judged_by_the_database_clock(pg):
    from app.worker.lease import db_now, try_acquire

    factory, _, _ = pg
    async with factory() as s:
        db_time = await db_now(s)
        assert abs(db_time - time.time()) < 5                                # same host here; the SOURCE is what matters
        a = await try_acquire(s, "A", 60)
        assert a.acquired
        row = (await s.execute(text("SELECT expires_at FROM worker_leases"))).scalar_one()
        assert 55 < row - db_time < 65


async def test_the_fence_holds_a_share_lock_so_a_takeover_cannot_slip_in_before_the_commit(pg):
    """Worker A checks the fence WITH lock=True inside its write transaction. Until that transaction ends, worker B's
    takeover (an UPDATE of the same row) must BLOCK - it cannot change the epoch between A's check and A's commit."""
    from app.worker.lease import LeaseKeeper, try_acquire

    factory, _, _ = pg
    a = LeaseKeeper(factory, owner_id="A", ttl_seconds=60, heartbeat_seconds=3600)
    assert await a.acquire()

    async def takeover():
        async with factory() as sb:
            return await try_acquire(sb, "B", 60, now=time.time() + 10_000)      # looks expired to B

    async with factory() as sa_:
        await a.check_db(sa_, lock=True)                                         # FOR SHARE held until this txn ends
        b = asyncio.create_task(takeover())
        await asyncio.sleep(0.6)
        assert not b.done(), "the takeover must be blocked while A's fenced write transaction is open"
        await sa_.commit()                                                       # A's writes are durable ...
    state = await asyncio.wait_for(b, 10)
    assert state.acquired and state.epoch == 2                                   # ... and only THEN can B take over
    async with factory() as s3:
        from app.worker.lease import LeaseLost
        with pytest.raises(LeaseLost):
            await a.check_db(s3)                                                 # A is now fenced


# --- the driver's real limits ------------------------------------------------------------------------------------------------


async def test_5000_candles_upsert_on_asyncpg_and_large_gap_recovery(pg):
    """asyncpg allows 32767 bind parameters per statement; ~17 per candle row made 5000 rows one 85k-parameter INSERT."""
    from app.core.system_flags import DATA_GAP_HALT, active_flags
    from app.market.market_data_service import MarketDataService
    from app.models.market import MarketCandle
    from tests.helpers_market import FakeHyperliquid, INTERVAL, T0, clock_after_bar, make_raw_candle

    factory, _, _ = pg
    svc = MarketDataService(FakeHyperliquid(n_candles=1), clock_ms=lambda: clock_after_bar(5_100))
    async with factory() as s:
        assert await svc.upsert_candles(s, [make_raw_candle(i) for i in range(5_000)]) == 5_000
        assert (await s.execute(select(func.count()).select_from(MarketCandle))).scalar_one() == 5_000

    fake = FakeHyperliquid(n_candles=3_400)
    svc2 = MarketDataService(fake, clock_ms=lambda: clock_after_bar(3_400))
    from app.core.config import get_settings
    old = get_settings().gap_check_window_bars
    get_settings().gap_check_window_bars = 6_000
    try:
        async with factory() as s:
            await s.execute(text("DELETE FROM market_candles WHERE open_time >= :a AND open_time < :b"),
                            {"a": T0 + 400 * INTERVAL, "b": T0 + 2_400 * INTERVAL})
            await s.commit()
            report = await svc2.recover_gaps(s)
            assert report.recovered and DATA_GAP_HALT not in await active_flags(s)
    finally:
        get_settings().gap_check_window_bars = old


async def test_confirmed_candle_is_immutable_against_a_late_frame_on_postgres(pg):
    from app.market.market_data_service import MarketDataService
    from app.models.market import MarketCandle
    from tests.helpers_market import FakeHyperliquid, T0, INTERVAL, clock_after_bar

    factory, _, _ = pg
    fake = FakeHyperliquid(n_candles=300)
    svc = MarketDataService(fake, clock_ms=lambda: clock_after_bar(299))
    async with factory() as s:
        await svc.sync_recent_candles(s, lookback_candles=300)
        ot = T0 + 299 * INTERVAL
        before = (await s.execute(select(MarketCandle.close).where(MarketCandle.open_time == ot))).scalar_one()
        late = dict(fake.candles[299]); late.update(c="1.5", h="2", l="0.5", o="1", v="3")
        await svc.upsert_candles(s, [late], now_ms=ot + 5_000)
        after, final = (await s.execute(select(MarketCandle.close, MarketCandle.is_final).where(MarketCandle.open_time == ot))).one()
        assert after == before and final is True


# --- PG-native triggers -------------------------------------------------------------------------------------------------------------


async def test_pg_triggers_protect_the_sealed_holdout_and_oos_results(pg):
    from datetime import datetime, timezone
    from app.models.research import Experiment, OosEvaluation, ResearchEpoch
    from app.models.strategy import Strategy, StrategyVersion
    from app.models.enums import StrategyFamily

    factory, engine, _ = pg
    async with factory() as s:
        epoch = ResearchEpoch(epoch_id="EP-PG", symbol="SOL", timeframe="1m", start_ms=0, end_ms=100, n_candles=10,
                              dataset_fingerprint="fp-pg", train_end_ms=5, validation_end_ms=8, oos_start_ms=9, oos_end_ms=100,
                              oos_fingerprint="fp-pg", active=True)
        s.add(epoch)
        strat = Strategy(code="S-PG", family=StrategyFamily.MOMENTUM, name="pg")
        s.add(strat)
        await s.flush()
        ver = StrategyVersion(strategy_id=strat.id, version=1, generation=1, dna={"k": 1})
        s.add(ver)
        await s.flush()
        s.add(Experiment(experiment_id="EXP-PG", kind="oos", code_version="c", schema_version="s", random_seed=1))
        s.add(OosEvaluation(strategy_version_id=ver.id, dataset_fingerprint="fp-pg", experiment_id="EXP-PG", oos_score=0.5, metrics={}))
        await s.commit()

    async def raw(sql):
        async with engine.begin() as conn:
            await conn.execute(text(sql))

    with pytest.raises(DBAPIError, match="sealed"):
        await raw("UPDATE research_epochs SET oos_end_ms = 999 WHERE epoch_id = 'EP-PG'")
    await raw("UPDATE research_epochs SET active = false WHERE epoch_id = 'EP-PG'")          # superseding is allowed
    with pytest.raises(DBAPIError, match="never be deleted"):
        await raw("DELETE FROM research_epochs WHERE epoch_id = 'EP-PG'")
    with pytest.raises(DBAPIError, match="never be deleted"):
        await raw("DELETE FROM experiments WHERE experiment_id = 'EXP-PG'")
    with pytest.raises(DBAPIError, match="write-once"):
        await raw("UPDATE oos_evaluations SET oos_score = 1.0")
    with pytest.raises(DBAPIError, match="write-once"):
        await raw("DELETE FROM oos_evaluations")
    with pytest.raises(DBAPIError, match="immutable"):
        await raw("UPDATE strategy_versions SET dna = '{\"k\": 2}'")                         # the pre-existing DNA trigger


# --- concurrency on the unique constraints ---------------------------------------------------------------------------------------------


async def test_two_workers_deciding_the_same_agent_candle_concurrently_one_wins(pg):
    from app.agents.decision_loop import decision_id_for
    from app.models.decision import Decision
    from app.models.enums import Bias, RiskDecision
    from tests.helpers_agents import make_agents, make_dna
    from datetime import datetime, timezone

    factory, _, _ = pg
    async with factory() as s:
        (agent,) = await make_agents(s, [make_dna()])
        agent_id, version_id = agent.id, agent.strategy_version_id

    async def decide(salt):
        async with factory() as s:
            s.add(Decision(id=uuid.uuid4(), agent_id=agent_id, strategy_version_id=version_id, market_candle_open_time=1_700_000_000_000,
                           market_timestamp=datetime.now(timezone.utc), agent_signal=Bias.LONG, agent_signal_confidence=0.5,
                           agent_signal_reasoning={"salt": salt}, final_signal=Bias.LONG, risk_decision=RiskDecision.APPROVED,
                           risk_reasoning={}))
            await s.commit()

    results = await asyncio.gather(*(decide(i) for i in range(6)), return_exceptions=True)
    assert sum(r is None for r in results) == 1
    assert all(isinstance(r, IntegrityError) for r in results if r is not None)


async def test_the_database_rejects_a_second_open_position_for_one_agent_concurrently(pg):
    from datetime import datetime, timezone
    from app.models.enums import Side
    from app.models.trading import Position
    from tests.helpers_agents import make_agents, make_dna

    factory, _, _ = pg
    async with factory() as s:
        (agent,) = await make_agents(s, [make_dna()])
        agent_id = agent.id

    async def open_one():
        async with factory() as s:
            s.add(Position(agent_id=agent_id, symbol="SOL", side=Side.LONG, quantity=1, entry_price=100, is_open=True,
                           opened_at=datetime.now(timezone.utc)))
            await s.commit()

    results = await asyncio.gather(*(open_one() for _ in range(5)), return_exceptions=True)
    assert sum(r is None for r in results) == 1 and all(isinstance(r, IntegrityError) for r in results if r is not None)


# --- pool + session settings -----------------------------------------------------------------------------------------------------------


async def test_pool_exhaustion_fails_fast_instead_of_hanging(pg_database):
    engine = create_async_engine(pg_database, pool_size=2, max_overflow=0, pool_timeout=1)
    try:
        c1, c2 = await engine.connect(), await engine.connect()
        t0 = time.monotonic()
        with pytest.raises(PoolTimeout):
            await engine.connect()
        assert time.monotonic() - t0 < 3
        await c1.close()
        c3 = await engine.connect()                       # capacity is returned as soon as a connection is released
        await c3.close(); await c2.close()
    finally:
        await engine.dispose()


async def test_session_timeouts_are_applied_to_every_pooled_connection(pg_database, monkeypatch):
    from app.core.config import get_settings
    from app.core.database import postgres_connect_args

    s = get_settings()
    monkeypatch.setattr(s, "database_lock_timeout_ms", 1234)
    monkeypatch.setattr(s, "database_idle_in_transaction_timeout_ms", 45_000)
    engine = create_async_engine(pg_database, connect_args=postgres_connect_args(s))
    try:
        async with engine.connect() as conn:
            assert (await conn.execute(text("SHOW lock_timeout"))).scalar_one() in ("1234ms", "1.234s")
            assert (await conn.execute(text("SHOW idle_in_transaction_session_timeout"))).scalar_one() == "45s"
            assert (await conn.execute(text("SHOW application_name"))).scalar_one() == "trading-lab"
    finally:
        await engine.dispose()


async def test_a_lock_wait_times_out_instead_of_blocking_forever(pg_database, monkeypatch):
    from app.core.config import get_settings
    from app.core.database import postgres_connect_args

    assert _alembic(pg_database, "upgrade", "head").returncode == 0
    s = get_settings()
    monkeypatch.setattr(s, "database_lock_timeout_ms", 300)
    engine = create_async_engine(pg_database, connect_args=postgres_connect_args(s))
    try:
        async with engine.begin() as setup:
            await setup.execute(text("INSERT INTO worker_leases (name, owner_id, expires_at, epoch, created_at, updated_at) "
                                     "VALUES ('x','o',1e18,1,now(),now())"))
        holder = await engine.connect()
        await holder.execute(text("UPDATE worker_leases SET owner_id='holder' WHERE name='x'"))       # row lock held
        async with engine.connect() as waiter:
            t0 = time.monotonic()
            with pytest.raises(DBAPIError, match="lock timeout|could not obtain lock"):
                await waiter.execute(text("UPDATE worker_leases SET owner_id='waiter' WHERE name='x'"))
            assert time.monotonic() - t0 < 3
        await holder.rollback(); await holder.close()
    finally:
        await engine.dispose()


# --- CHECK constraints + migration pre-flight on PostgreSQL ------------------------------------------------------------------------------------


async def test_check_constraints_are_enforced_by_postgres_itself(pg):
    from tests.helpers_agents import make_agents, make_dna
    from app.models.enums import OrderStatus, ExecutionVenue, Side
    from app.models.trading import Order

    factory, engine, _ = pg
    async with factory() as s:
        (agent,) = await make_agents(s, [make_dna()])
        agent_id = agent.id

    async def raw(sql, **params):
        async with engine.begin() as conn:
            await conn.execute(text(sql), params)

    with pytest.raises(DBAPIError, match="ck_agents_balance_nonneg"):
        await raw("UPDATE agents SET balance = -1")
    with pytest.raises(DBAPIError, match="ck_agents_bad_debt_nonneg"):
        await raw("UPDATE agents SET bad_debt = -1")
    with pytest.raises(DBAPIError, match="ck_candles_ohlcv_sane"):
        await raw("INSERT INTO market_candles (id,symbol,timeframe,open_time,close_time,open,high,low,close,volume,is_final,source,created_at,updated_at)"
                  " VALUES (:i,'SOL','1m',1,2,100,99,101,100,1,true,'x',now(),now())", i=uuid.uuid4())
    with pytest.raises(DBAPIError, match="ck_worker_cycles_status"):
        await raw("INSERT INTO worker_cycles (id,cycle_id,candle_timestamp,cycle_started_at,completed,status,attempts,created_at,updated_at)"
                  " VALUES (:i,'c',1,1,false,'BOGUS',1,now(),now())", i=uuid.uuid4())

    def order(**kw):
        base = dict(agent_id=agent_id, client_order_id=f"c-{uuid.uuid4().hex}", symbol="SOL", side=Side.LONG, quantity=1.0,
                    venue=ExecutionVenue.PAPER, status=OrderStatus.FAILED)
        base.update(kw)
        return Order(**base)

    async with factory() as s:
        s.add(order(status=OrderStatus.FILLED))
        with pytest.raises(IntegrityError, match="ck_orders_filled_has_a_fill"):
            await s.flush()
        await s.rollback()
        s.add(order(status=OrderStatus.PENDING))
        await s.commit()
        s.add(order(status=OrderStatus.PENDING))
        with pytest.raises(IntegrityError, match="uq_order_one_pending_entry_per_agent"):
            await s.flush()
        await s.rollback()

    # ... including under REAL concurrency: many workers each try to leave a pending entry for one agent
    async with factory() as s:
        await s.execute(text("DELETE FROM orders"))
        await s.commit()

    async def pend():
        async with factory() as s:
            s.add(order(status=OrderStatus.PENDING))
            await s.commit()

    res = await asyncio.gather(*(pend() for _ in range(6)), return_exceptions=True)
    assert sum(r is None for r in res) == 1 and all(isinstance(r, IntegrityError) for r in res if r is not None)


async def test_migration_preflight_refuses_on_postgres_and_changes_nothing(pg_database):
    assert _alembic(pg_database, "upgrade", "a6c2e8f4b0d7").returncode == 0
    conn = await asyncpg.connect(pg_database.replace("postgresql+asyncpg://", "postgresql://"))
    sid, vid, aid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await conn.execute("INSERT INTO strategies (id, code, family, name, description, created_at, updated_at) "
                       "VALUES ($1,'C1','MOMENTUM','n','',now(),now())", sid)
    await conn.execute("INSERT INTO strategy_versions (id, strategy_id, version, generation, dna, stage, proposed_by, hypothesis, created_at, updated_at) "
                       "VALUES ($1,$2,1,1,'{}'::json,'PAPER','system','',now(),now())", vid, sid)
    await conn.execute("INSERT INTO agents (id, identifier, generation, strategy_version_id, status, starting_balance, balance, equity, "
                       "realized_pnl, fees_paid, funding_paid, peak_equity, max_drawdown, day_start_equity, day_start_date, trade_count, "
                       "daily_trade_count, is_professional, best_milestone_multiple, created_at, updated_at) "
                       "VALUES ($1,'GEN01-AG0001',1,$2,'ACTIVE',100,-5,-5,0,0,0,100,0,100,current_date,0,0,false,1,now(),now())", aid, vid)
    await conn.close()
    r = _alembic(pg_database, "upgrade", "head")
    assert r.returncode != 0 and "ck_agents_balance_nonneg" in r.stderr and "refusing to add database constraints" in r.stderr
    conn = await asyncpg.connect(pg_database.replace("postgresql+asyncpg://", "postgresql://"))
    assert await conn.fetchval("SELECT version_num FROM alembic_version") == "a6c2e8f4b0d7"          # nothing applied
    await conn.execute("UPDATE agents SET balance = 5, equity = 5")
    await conn.close()
    assert _alembic(pg_database, "upgrade", "head").returncode == 0
