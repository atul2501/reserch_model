"""WebSocket -> store glue, and an end-to-end paper-mode smoke test of the real worker entrypoint."""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import get_settings
from app.market.market_data_service import MarketDataService
from app.market.ws_ingest import WsCandleIngestor
from app.models.market import MarketCandle
from app.models.system import SystemStatus, WorkerCycle, WorkerLease
from tests.helpers_market import INTERVAL, T0, FakeHyperliquid, clock_after_bar, make_raw_candle


async def test_previous_bar_is_confirmed_the_moment_the_exchange_starts_the_next_one(db_session, db_engine):
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    fake = FakeHyperliquid(n_candles=0)
    svc = MarketDataService(fake, clock_ms=lambda: T0 + 5 * INTERVAL + 10_000)     # clock is 10s into bar 5
    ingest = WsCandleIngestor(factory, svc)
    b4, b5 = make_raw_candle(4), make_raw_candle(5)
    await ingest([b4])                                     # bar 4 still forming (its close time is in the future for this clock? no: it closed, but grace)
    await ingest([b5])                                     # bar 5 starts -> bar 4 must now be final
    rows = {r.open_time: r for r in (await db_session.execute(select(MarketCandle))).scalars().all()}
    assert rows[T0 + 4 * INTERVAL].is_final is True
    assert rows[T0 + 5 * INTERVAL].is_final is False      # the forming bar is never final
    assert svc.is_confirmed(int(b5["T"])) is False


async def test_paper_mode_worker_smoke_run(db_session, db_engine, monkeypatch, capsys):
    """`python -m scripts.run_cycle --once` in paper mode against a fake exchange: candle -> features ->
    council skipped -> agents -> paper execution -> cycle recorded, lease released, status published."""
    import scripts.run_cycle as worker
    from tests.helpers_agents import make_agents, make_dna
    s = get_settings()
    for k, v in dict(market_ws_enabled=False, council_enabled=False, paper_latency_ms=0, paper_latency_jitter_ms=0).items():
        monkeypatch.setattr(s, k, v)
    assert s.trading_mode.value == "paper"

    fake = FakeHyperliquid(n_candles=400)
    monkeypatch.setattr(worker, "MarketDataService", lambda: MarketDataService(fake, clock_ms=lambda: clock_after_bar(399)))
    await make_agents(db_session, [make_dna(), make_dna()], generation=1)
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "AsyncSessionLocal", factory)
    monkeypatch.setattr("app.worker.lease.os.getpid", lambda: 4242)
    monkeypatch.setattr(worker, "last_confirmed_open_time", lambda *a, **k: T0 + 399 * INTERVAL)

    await asyncio.wait_for(worker.main(run_once=True), timeout=60)

    async with factory() as db:
        cycle = (await db.execute(select(WorkerCycle))).scalar_one()
        assert cycle.status == "COMPLETED" and cycle.candle_timestamp == T0 + 399 * INTERVAL and cycle.agents_processed == 2
        lease = await db.get(WorkerLease, "decision-worker")
        assert lease.expires_at == 0.0                     # released on shutdown: the next worker can start immediately
        status = await db.get(SystemStatus, "worker")
        assert status is not None and status.payload["execution_venue"] == "PAPER" and status.payload["metrics_text"] is not None


async def test_second_worker_refuses_to_trade_while_the_lease_is_held(db_session, db_engine, monkeypatch):
    import scripts.run_cycle as worker
    from app.worker.lease import try_acquire
    s = get_settings()
    monkeypatch.setattr(s, "market_ws_enabled", False)
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "AsyncSessionLocal", factory)
    monkeypatch.setattr(worker, "MarketDataService", lambda: MarketDataService(FakeHyperliquid(n_candles=10)))
    await try_acquire(db_session, "some-other-worker", ttl_seconds=300)
    with pytest.raises(worker.WorkerAlreadyActive):
        await worker.main(run_once=True)
    assert (await db_session.execute(select(WorkerCycle))).first() is None         # it did not trade
