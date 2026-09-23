"""Closed-candle data integrity (spec phases 1, 18): only confirmed candles
reach trading, exact boundaries, duplicate protection, gap recovery/halt."""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.core.system_flags import DATA_GAP_HALT, active_flags
from app.market.market_data_service import MarketDataService
from app.models.market import FundingRate, MarketCandle
from tests.helpers_market import INTERVAL, T0, FakeHyperliquid, clock_after_bar, make_raw_candle


def _service(fake: FakeHyperliquid, now_ms: int) -> MarketDataService:
    return MarketDataService(fake, clock_ms=lambda: now_ms)


async def test_open_candle_is_stored_but_never_returned_for_trading(db_session):
    fake = FakeHyperliquid(n_candles=300)
    # 30s into bar 299 -> bar 299 is still OPEN, bar 298 is the last confirmed one.
    now = T0 + 299 * INTERVAL + 30_000
    svc = _service(fake, now)
    await svc.sync_recent_candles(db_session, lookback_candles=300)

    open_bar = (await db_session.execute(select(MarketCandle).where(MarketCandle.open_time == T0 + 299 * INTERVAL))).scalar_one()
    assert open_bar.is_final is False

    frame = await svc.get_recent_candles(db_session, limit=500)  # trading default = confirmed only
    assert int(frame["open_time"].iloc[-1]) == T0 + 298 * INTERVAL
    assert (T0 + 299 * INTERVAL) not in set(frame["open_time"])
    assert await svc.latest_confirmed_open_time(db_session) == T0 + 298 * INTERVAL

    display = await svc.get_recent_candles(db_session, limit=500, confirmed_only=False)
    assert int(display["open_time"].iloc[-1]) == T0 + 299 * INTERVAL  # explicit opt-in only


async def test_exact_minute_boundary_and_grace(db_session):
    fake = FakeHyperliquid(n_candles=300)
    bar = T0 + 10 * INTERVAL
    close = bar + INTERVAL - 1
    svc = _service(fake, close)
    grace = svc._settings.candle_finality_grace_ms
    assert svc.is_confirmed(close, now_ms=close + grace - 1) is False   # 1ms early
    assert svc.is_confirmed(close, now_ms=close + grace) is True        # exact confirmation instant
    assert svc.is_confirmed(close, now_ms=bar + 30_000) is False         # mid-bar


async def test_confirmed_candle_is_processed_after_it_closes(db_session):
    fake = FakeHyperliquid(n_candles=300)
    svc = _service(fake, clock_after_bar(299))
    await svc.sync_recent_candles(db_session, lookback_candles=300)
    assert await svc.latest_confirmed_open_time(db_session) == T0 + 299 * INTERVAL


async def test_duplicate_sync_is_idempotent(db_session):
    fake = FakeHyperliquid(n_candles=300)
    svc = _service(fake, clock_after_bar(299))
    await svc.sync_recent_candles(db_session, lookback_candles=300)
    n1 = (await db_session.execute(select(func.count()).select_from(MarketCandle))).scalar_one()
    await svc.sync_recent_candles(db_session, lookback_candles=300)
    n2 = (await db_session.execute(select(func.count()).select_from(MarketCandle))).scalar_one()
    assert n1 == n2 and n1 >= 299


async def test_confirmed_bar_never_reverts_to_open(db_session):
    fake = FakeHyperliquid(n_candles=300)
    svc = _service(fake, clock_after_bar(299))
    await svc.sync_recent_candles(db_session, lookback_candles=300)
    # A stale/out-of-order push carrying an early clock must not un-confirm the bar.
    await svc.upsert_candles(db_session, [fake.candles[299]], now_ms=T0 + 299 * INTERVAL + 10)
    row = (await db_session.execute(select(MarketCandle).where(MarketCandle.open_time == T0 + 299 * INTERVAL))).scalar_one()
    assert row.is_final is True


async def test_funding_context_only_attributed_to_newest_confirmed_bar(db_session):
    fake = FakeHyperliquid(n_candles=300)
    svc = _service(fake, clock_after_bar(299))
    await svc.sync_recent_candles(db_session, lookback_candles=300)
    rows = (await db_session.execute(select(MarketCandle).where(MarketCandle.funding_rate.is_not(None)))).scalars().all()
    assert [r.open_time for r in rows] == [T0 + 299 * INTERVAL]  # not stamped across history


async def test_funding_history_is_persisted_and_idempotent(db_session):
    fake = FakeHyperliquid(n_candles=300)
    svc = _service(fake, clock_after_bar(299))
    assert await svc.sync_funding_history(db_session) > 0
    n1 = (await db_session.execute(select(func.count()).select_from(FundingRate))).scalar_one()
    await svc.sync_funding_history(db_session)
    n2 = (await db_session.execute(select(func.count()).select_from(FundingRate))).scalar_one()
    assert n1 == n2 > 0


async def test_gap_is_detected_backfilled_and_trading_resumes(db_session):
    fake = FakeHyperliquid(n_candles=300)
    svc = _service(fake, clock_after_bar(299))
    await svc.sync_recent_candles(db_session, lookback_candles=300)
    # Punch a 3-bar hole into the store.
    hole = [T0 + i * INTERVAL for i in (150, 151, 152)]
    for ot in hole:
        row = (await db_session.execute(select(MarketCandle).where(MarketCandle.open_time == ot))).scalar_one()
        await db_session.delete(row)
    await db_session.commit()
    assert await svc.detect_gaps(db_session) == hole

    report = await svc.recover_gaps(db_session)
    assert report.recovered and report.backfilled >= 3 and not report.halted
    assert await svc.detect_gaps(db_session) == []
    assert DATA_GAP_HALT not in await active_flags(db_session)


async def test_unrecoverable_gap_halts_new_entries_then_clears_when_healed(db_session):
    fake = FakeHyperliquid(n_candles=300)
    svc = _service(fake, clock_after_bar(299))
    await svc.sync_recent_candles(db_session, lookback_candles=300)
    ot = T0 + 200 * INTERVAL
    row = (await db_session.execute(select(MarketCandle).where(MarketCandle.open_time == ot))).scalar_one()
    await db_session.delete(row)
    await db_session.commit()
    fake.hidden.add(ot)  # exchange cannot supply the bar

    report = await svc.recover_gaps(db_session)
    assert report.halted and report.missing_after == [ot]
    assert DATA_GAP_HALT in await active_flags(db_session)

    fake.hidden.clear()  # exchange now has it
    report = await svc.recover_gaps(db_session)
    assert report.recovered
    assert DATA_GAP_HALT not in await active_flags(db_session)


async def test_backfill_failure_still_halts(db_session):
    fake = FakeHyperliquid(n_candles=300)
    svc = _service(fake, clock_after_bar(299))
    await svc.sync_recent_candles(db_session, lookback_candles=300)
    ot = T0 + 100 * INTERVAL
    row = (await db_session.execute(select(MarketCandle).where(MarketCandle.open_time == ot))).scalar_one()
    await db_session.delete(row)
    await db_session.commit()
    fake.fail_candles = True
    report = await svc.recover_gaps(db_session)
    assert report.halted
    assert DATA_GAP_HALT in await active_flags(db_session)


async def test_wait_for_confirmed_candle_polls_until_exchange_publishes(db_session, monkeypatch):
    fake = FakeHyperliquid(n_candles=300)
    target = T0 + 299 * INTERVAL
    fake.hidden.add(target)  # exchange late publishing the closed bar
    svc = _service(fake, clock_after_bar(299))
    monkeypatch.setattr(svc._settings, "candle_poll_interval_seconds", 0.01)
    await svc.sync_recent_candles(db_session, lookback_candles=300)
    assert await svc.latest_confirmed_open_time(db_session) == target - INTERVAL

    fake.on_call = lambda n: fake.hidden.discard(target) if n >= 3 else None
    assert await svc.wait_for_confirmed_candle(db_session, target, deadline_seconds=2) is True


async def test_wait_for_confirmed_candle_gives_up_at_deadline(db_session, monkeypatch):
    fake = FakeHyperliquid(n_candles=300)
    target = T0 + 299 * INTERVAL
    fake.hidden.add(target)
    svc = _service(fake, clock_after_bar(299))
    monkeypatch.setattr(svc._settings, "candle_poll_interval_seconds", 0.01)
    await svc.sync_recent_candles(db_session, lookback_candles=300)
    assert await svc.wait_for_confirmed_candle(db_session, target, deadline_seconds=0.05) is False
