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


# --- bind-parameter limit, confirmed-bar immutability, paged recovery, pre-execution finality ------------------


def _raws(n: int, start: int = 0) -> list[dict]:
    return [make_raw_candle(i) for i in range(start, start + n)]


ASYNCPG_MAX_BINDS = 32_767   # the production driver's hard per-statement limit (SQLite's default is 32_766)


def _spy_bind_counts(db_session, monkeypatch) -> list[int]:
    """Records the bind-parameter count of every INSERT sent through the session, whatever the backend."""
    from sqlalchemy.dialects import postgresql

    real = db_session.execute
    counts: list[int] = []

    async def spy(stmt, *a, **kw):
        if getattr(stmt, "is_insert", False):
            counts.append(len(stmt.compile(dialect=postgresql.dialect()).params))
        return await real(stmt, *a, **kw)

    monkeypatch.setattr(db_session, "execute", spy)
    return counts


async def test_upsert_never_exceeds_the_bind_parameter_limit_of_a_single_statement(db_session, monkeypatch):
    counts = _spy_bind_counts(db_session, monkeypatch)
    svc = _service(FakeHyperliquid(n_candles=1), clock_after_bar(5_100))
    written = await svc.upsert_candles(db_session, _raws(5_000))
    assert written == 5_000
    assert len(counts) > 1 and max(counts) <= ASYNCPG_MAX_BINDS       # 5000 rows x ~17 binds would be 85k in ONE statement
    assert (await db_session.execute(select(func.count()).select_from(MarketCandle))).scalar_one() == 5_000


async def test_backfill_history_pages_and_chunks_a_multi_day_range(db_session):
    fake = FakeHyperliquid(n_candles=6_000)
    svc = _service(fake, clock_after_bar(6_000))
    total = await svc.backfill_history(db_session, T0, T0 + 6_000 * INTERVAL, page_bars=4_000)
    assert total >= 6_000                      # adjacent inclusive pages may re-send one boundary bar (idempotent)
    assert (await db_session.execute(select(func.count()).select_from(MarketCandle))).scalar_one() == 6_000


async def test_large_gap_recovers_in_pages_and_resumes(db_session, monkeypatch):
    counts = _spy_bind_counts(db_session, monkeypatch)
    """A 2000-bar hole (> one 1000-bar recovery page AND > the ~1900-row bind-limit ceiling of a single INSERT)
    must be backfilled page by page, validated for continuity, persisted, and trading must resume."""
    from app.core.config import get_settings

    fake = FakeHyperliquid(n_candles=3_400)
    svc = _service(fake, clock_after_bar(3_400))
    monkeypatch.setattr(get_settings(), "gap_check_window_bars", 1_200)   # sees 1000 recent + 200 pre-hole bars
    await svc.upsert_candles(db_session, [make_raw_candle(i) for i in range(3_400) if not (400 <= i < 2_400)])
    await db_session.commit()
    from app.core.system_flags import set_flag
    await set_flag(db_session, DATA_GAP_HALT, True, reason="test", set_by="test")   # a halt raised earlier by the outage
    await db_session.commit()
    fake.calls.clear()

    report = await svc.recover_gaps(db_session)

    assert len(report.missing_before) == 2_000
    assert report.recovered and not report.halted and report.backfilled >= 2_000
    assert len([c for c in fake.calls if c[0] == "candles"]) >= 2          # paged, not one giant request
    assert await svc.detect_gaps(db_session) == []                          # continuity validated after persisting
    assert DATA_GAP_HALT not in await active_flags(db_session)              # ... and trading resumes
    assert (await db_session.execute(select(func.count()).select_from(MarketCandle))).scalar_one() == 3_400
    assert max(counts) <= ASYNCPG_MAX_BINDS


async def test_gap_backfill_failure_rolls_back_and_halts(db_session):
    fake = FakeHyperliquid(n_candles=300)
    svc = _service(fake, clock_after_bar(299))
    await svc.sync_recent_candles(db_session, lookback_candles=300)
    count = lambda: db_session.execute(select(func.count()).select_from(MarketCandle))  # noqa: E731
    total = (await count()).scalar_one()
    ot = T0 + 150 * INTERVAL
    row = (await db_session.execute(select(MarketCandle).where(MarketCandle.open_time == ot))).scalar_one()
    await db_session.delete(row)
    await db_session.commit()
    fake.fail_candles = True
    report = await svc.recover_gaps(db_session)
    assert report.halted and DATA_GAP_HALT in await active_flags(db_session)
    # the session is usable afterwards (no aborted transaction left behind) and nothing was half-written
    assert (await count()).scalar_one() == total - 1


async def test_confirmed_bar_is_immutable_against_a_late_partial_frame(db_session):
    from app.core import metrics

    metrics.reset()
    fake = FakeHyperliquid(n_candles=300)
    svc = _service(fake, clock_after_bar(299))
    await svc.sync_recent_candles(db_session, lookback_candles=300)
    ot = T0 + 299 * INTERVAL
    before = (await db_session.execute(select(MarketCandle).where(MarketCandle.open_time == ot))).scalar_one()
    snapshot = (before.open, before.high, before.low, before.close, before.volume)
    assert before.is_final

    late = dict(fake.candles[299])                       # a late, PARTIAL (non-final) frame for the same bar
    late.update(o="1", h="2", l="0.5", c="1.5", v="3")
    await svc.upsert_candles(db_session, [late], now_ms=ot + 10_000)   # clock says the bar is still open
    await db_session.refresh(before)
    assert (before.open, before.high, before.low, before.close, before.volume) == snapshot
    assert before.is_final is True                        # never reverts to open
    assert metrics.counter_value("candle_revision_ignored", incoming_final="false") == 1

    revised = dict(late)                                  # even a "final" REST re-fetch with different values is ignored
    await svc.upsert_candles(db_session, [revised], now_ms=clock_after_bar(299))
    await db_session.refresh(before)
    assert before.close == snapshot[3]
    assert metrics.counter_value("candle_revision_ignored", incoming_final="true") == 1


async def test_open_bar_is_still_updated_until_it_is_confirmed(db_session):
    fake = FakeHyperliquid(n_candles=300)
    now = T0 + 299 * INTERVAL + 20_000
    svc = _service(fake, now)
    await svc.sync_recent_candles(db_session, lookback_candles=300)
    ot = T0 + 299 * INTERVAL
    upd = dict(fake.candles[299])
    upd.update(c="123.45")
    await svc.upsert_candles(db_session, [upd], now_ms=now)
    row = (await db_session.execute(select(MarketCandle).where(MarketCandle.open_time == ot))).scalar_one()
    assert row.close == 123.45 and row.is_final is False


async def test_funding_context_can_still_attach_to_a_confirmed_bar(db_session):
    fake = FakeHyperliquid(n_candles=300)
    svc = _service(fake, clock_after_bar(299))
    await svc.upsert_candles(db_session, [fake.candles[299]])          # confirmed without funding context
    await svc.upsert_candles(db_session, [fake.candles[299]], funding_context={"funding": "0.0001", "openInterest": "42"})
    row = (await db_session.execute(select(MarketCandle).where(MarketCandle.open_time == T0 + 299 * INTERVAL))).scalar_one()
    assert row.funding_rate == pytest.approx(0.0001) and row.open_interest == 42.0 and row.is_final


async def test_verify_candle_final_gate(db_session):
    from app.market.market_data_service import CandleNotFinalError

    fake = FakeHyperliquid(n_candles=300)
    now = T0 + 299 * INTERVAL + 20_000                                   # bar 299 still open, 298 confirmed
    svc = _service(fake, now)
    await svc.sync_recent_candles(db_session, lookback_candles=300)
    good = T0 + 298 * INTERVAL
    row = (await db_session.execute(select(MarketCandle).where(MarketCandle.open_time == good))).scalar_one()
    await svc.verify_candle_final(db_session, good, expected_close=row.close)          # ok
    with pytest.raises(CandleNotFinalError):
        await svc.verify_candle_final(db_session, T0 + 299 * INTERVAL)                 # still forming
    with pytest.raises(CandleNotFinalError):
        await svc.verify_candle_final(db_session, T0 + 5_000 * INTERVAL)               # absent / future
    with pytest.raises(CandleNotFinalError):
        await svc.verify_candle_final(db_session, good, expected_close=row.close + 1)  # changed under our feet
