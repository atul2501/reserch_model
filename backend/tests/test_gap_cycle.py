"""Gap recovery through the REAL cycle path (spec phase 14):

    gap -> backfill -> validate continuity -> persist -> resume
    gap -> backfill FAILS -> DATA_GAP_HALT -> NEW entries refused, open positions still protected
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.system_flags import DATA_GAP_HALT, active_flags
from app.execution.paper_adapter import PaperExecutionAdapter
from app.market.market_data_service import MarketDataService
from app.models.market import MarketCandle
from app.models.trading import Position, Trade
from app.worker import cycle as cycle_mod
from tests.helpers_market import INTERVAL, T0, FakeHyperliquid, clock_after_bar
from tests.test_council_failclosed import _seed_always_long_population

pytestmark = pytest.mark.usefixtures("immediate_fills")   # position mechanics; see conftest.immediate_fills


@pytest.fixture
def paper(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "council_enabled", False)
    monkeypatch.setattr(s, "paper_latency_ms", 0)
    return s


async def _open_positions_at_bar_398(db, fake):
    market = MarketDataService(fake, clock_ms=lambda: clock_after_bar(398))
    await _seed_always_long_population(db)
    await market.sync_recent_candles(db, lookback_candles=400)
    outcomes = await cycle_mod.run_pending_cycles(db, market, None, execution_engine=PaperExecutionAdapter())
    assert outcomes[0].status == "COMPLETED"
    open_positions = (await db.execute(select(Position).where(Position.is_open.is_(True)))).scalars().all()
    assert len(open_positions) == 3, "precondition: every always-long agent opened a position"
    return open_positions


def _crash(fake, bar=399):
    c = dict(fake.candles[bar])
    c.update(o="90.0", h="90.5", l="40.0", c="41.0")      # a violent drop far through every ATR stop
    fake.candles[bar] = c


async def _delete_bar(db, i):
    row = (await db.execute(select(MarketCandle).where(MarketCandle.open_time == T0 + i * INTERVAL))).scalar_one()
    await db.delete(row)
    await db.commit()


async def test_unrecoverable_gap_halts_new_entries_but_open_positions_are_still_protected(db_session, paper):
    fake = FakeHyperliquid(n_candles=400)
    await _open_positions_at_bar_398(db_session, fake)
    positions_before = (await db_session.execute(select(func.count()).select_from(Position))).scalar_one()

    _crash(fake)
    await _delete_bar(db_session, 200)
    fake.hidden.add(T0 + 200 * INTERVAL)                  # the exchange cannot supply the missing bar
    market = MarketDataService(fake, clock_ms=lambda: clock_after_bar(399))

    outcomes = await cycle_mod.run_pending_cycles(db_session, market, None, execution_engine=PaperExecutionAdapter())

    assert DATA_GAP_HALT in await active_flags(db_session)
    assert outcomes and outcomes[-1].status == "COMPLETED" and DATA_GAP_HALT in (outcomes[-1].halt_reason or "")
    # protection still ran: every position was stopped out on the crash candle ...
    still_open = (await db_session.execute(select(Position).where(Position.is_open.is_(True)))).scalars().all()
    assert still_open == []
    trades = (await db_session.execute(select(Trade))).scalars().all()
    assert len(trades) == 3 and all(t.net_pnl < 0 for t in trades)
    # ... and NO new entry was placed even though every agent's entry rule is true on this bar:
    assert (await db_session.execute(select(func.count()).select_from(Position))).scalar_one() == positions_before


async def test_recovered_gap_resumes_trading(db_session, paper):
    fake = FakeHyperliquid(n_candles=400)
    await _open_positions_at_bar_398(db_session, fake)
    await _delete_bar(db_session, 200)
    fake.hidden.add(T0 + 200 * INTERVAL)
    market = MarketDataService(fake, clock_ms=lambda: clock_after_bar(399))
    await cycle_mod.run_pending_cycles(db_session, market, None, execution_engine=PaperExecutionAdapter())
    assert DATA_GAP_HALT in await active_flags(db_session)

    fake.hidden.clear()                                    # the exchange can now supply the bar
    report = await market.recover_gaps(db_session)         # gap -> backfill -> validate -> persist
    assert report.recovered and await market.detect_gaps(db_session) == []
    assert DATA_GAP_HALT not in await active_flags(db_session)       # ... -> resume
