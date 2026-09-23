"""Shadow mode (spec phase 26): real book, hypothetical fills, no orders ever."""
from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from app.core.config import Settings, TradingMode, get_settings
from app.execution.base import ExecutionRequest
from app.execution.paper_adapter import PaperExecutionAdapter
from app.execution.router import get_execution_engine
from app.execution.shadow_adapter import L2Book, ShadowExecutionAdapter, parse_book, walk_book
from app.models.enums import ExecutionVenue, OrderStatus, Side, StrategyStage
from app.models.trading import Order, Trade
from tests.helpers_agents import cycle, make_agents, make_context, make_dna


def book(bid=99.9, ask=100.1, depth=(5.0, 5.0, 50.0), t=1):
    return {"coin": "SOL", "time": t, "levels": [
        [{"px": str(round(bid - i * 0.1, 4)), "sz": str(sz), "n": 3} for i, sz in enumerate(depth)],
        [{"px": str(round(ask + i * 0.1, 4)), "sz": str(sz), "n": 3} for i, sz in enumerate(depth)],
    ]}


class FakeBook:
    def __init__(self, seq=None, fail=False):
        self.seq, self.calls, self.fail = list(seq or [book()]), 0, fail

    async def get_l2_book(self, coin):
        self.calls += 1
        if self.fail:
            raise RuntimeError("book feed down")
        return self.seq[min(self.calls - 1, len(self.seq) - 1)]


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "shadow_assumed_latency_ms", 1)
    monkeypatch.setattr(s, "shadow_book_ttl_seconds", 60.0)


def req(cid="s1", side=Side.LONG, qty=1.0, price=100.0, **kw):
    return ExecutionRequest(client_order_id=cid, agent_id="a", symbol="SOL", side=side, quantity=qty, leverage=1.0, reference_price=price, **kw)


def test_walk_book_is_volume_weighted_and_reports_partial_depth():
    lv = ((100.0, 1.0), (101.0, 1.0))
    assert walk_book(lv, 1.5) == (pytest.approx((100 + 0.5 * 101) / 1.5), 1.5)
    px, filled = walk_book(lv, 5.0)
    assert filled == 2.0 and px == pytest.approx(100.5)
    assert walk_book((), 1.0) == (None, 0.0)


async def test_shadow_fills_by_walking_the_real_book_not_the_paper_cost_model():
    a = ShadowExecutionAdapter(FakeBook([book(depth=(0.5, 0.5, 50.0))]))
    r = await a.submit_order(req(qty=1.0))
    # buys 0.5 @100.1 and 0.5 @100.2
    assert r.status == OrderStatus.FILLED and r.filled_price == pytest.approx(100.15)
    assert r.raw_response["sent_to_exchange"] is False and r.raw_response["depth_levels_used"] == 3
    assert r.raw_response["slippage_bps"] == pytest.approx((100.15 / 100 - 1) * 10_000)
    paper = await PaperExecutionAdapter().submit_order(req("p1", qty=1.0))
    assert r.filled_price != paper.filled_price                       # genuinely different mechanics


async def test_shorting_sells_into_the_bids_and_closing_a_long_sells_into_bids():
    a = ShadowExecutionAdapter(FakeBook())
    short = await a.submit_order(req("s", Side.SHORT, 1.0))
    close_long = await a.submit_order(req("c", Side.LONG, 1.0, reduce_only=True))
    assert short.filled_price == pytest.approx(99.9) == close_long.filled_price
    cover = await a.submit_order(req("cv", Side.SHORT, 1.0, reduce_only=True))
    assert cover.filled_price == pytest.approx(100.1)                    # covering a short buys the asks


async def test_partial_fill_when_depth_is_insufficient_but_exits_always_complete():
    a = ShadowExecutionAdapter(FakeBook([book(depth=(0.2, 0.2, 0.2))]))
    entry = await a.submit_order(req("e", qty=5.0))
    assert entry.status == OrderStatus.PARTIALLY_FILLED and entry.filled_quantity == pytest.approx(0.6)
    exit_ = await a.submit_order(req("x", qty=5.0, reduce_only=True, side=Side.LONG))
    assert exit_.status == OrderStatus.FILLED and exit_.filled_quantity == 5.0


async def test_expected_vs_actual_market_execution_is_recorded():
    a = ShadowExecutionAdapter(FakeBook([book(bid=99.9, ask=100.1, t=1), book(bid=100.4, ask=100.6, t=2)]))
    r = await a.submit_order(req())
    raw = r.raw_response
    assert raw["observed_mid_after_latency"] == pytest.approx(100.5)          # market moved while we "waited"
    assert raw["drift_after_latency_bps"] == pytest.approx(50.0, rel=0.02)
    assert raw["book_fetch_ms"] >= 0 and raw["assumed_latency_ms"] == 1 and r.latency_ms >= 1


async def test_one_book_snapshot_serves_all_agents_within_the_ttl():
    fb = FakeBook()
    a = ShadowExecutionAdapter(fb)
    for i in range(50):
        await a.submit_order(req(f"o{i}"))
    assert fb.calls == 2                                                      # book + after-latency book, once for 50 orders


async def test_entries_fail_closed_when_the_book_is_unavailable_but_exits_still_close():
    a = ShadowExecutionAdapter(FakeBook(fail=True))
    entry = await a.submit_order(req("e"))
    assert entry.status == OrderStatus.FAILED and entry.rejection_reason == "book_unavailable"
    exit_ = await a.submit_order(req("x", reduce_only=True))
    assert exit_.status == OrderStatus.FILLED and exit_.raw_response["fallback"] == "cost_model_book_unavailable"


async def test_duplicate_client_order_id_is_not_filled_twice():
    a = ShadowExecutionAdapter(FakeBook())
    assert (await a.submit_order(req("d"))).status == OrderStatus.FILLED
    assert (await a.submit_order(req("d"))).rejection_reason == "duplicate_client_order_id"


async def test_shadow_can_never_send_a_real_order_only_public_book_reads(monkeypatch):
    """Route the REAL HyperliquidClient through a recording transport: every request must be
    an `info` read of type l2Book; `/exchange` (order placement) must never be touched."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, request.content))
        if request.url.path != "/info":
            raise AssertionError(f"shadow mode touched {request.url.path}")
        import json
        assert json.loads(request.content)["type"] == "l2Book"
        return httpx.Response(200, json=book())

    from app.market.hyperliquid_client import HyperliquidClient
    client = HyperliquidClient(base_url="http://fake-hl")
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://fake-hl")
    a = ShadowExecutionAdapter(client)
    for i in range(3):
        await a.submit_order(req(f"n{i}"))
        await a.submit_order(req(f"m{i}", Side.SHORT, reduce_only=True))
    assert seen and {p for p, _ in seen} == {"/info"}
    await client.aclose()


def test_shadow_module_has_no_signing_or_order_placement_code():
    import ast, inspect
    import app.execution.shadow_adapter as m
    tree = ast.parse(inspect.getsource(m))
    imported = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not any(x.startswith(("eth_account", "web3", "hyperliquid")) and "hyperliquid_client" not in x for x in imported)
    assert "app.execution.live_adapter" not in imported
    strings = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and len(n.value) < 60}
    assert not any("/exchange" in s or "private_key" in s for s in strings)
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not names & {"hyperliquid_private_key", "hyperliquid_account_address", "sign_l1_action"}


def test_router_returns_the_shadow_adapter_for_shadow_mode_and_it_is_not_a_paper_subclass():
    eng = get_execution_engine(Settings(trading_mode=TradingMode.SHADOW))
    assert isinstance(eng, ShadowExecutionAdapter) and not isinstance(eng, PaperExecutionAdapter)
    assert eng.venue == ExecutionVenue.SHADOW


async def test_full_shadow_cycle_creates_hypothetical_orders_positions_and_shadow_stage_trades(db_session):
    a1, a2 = await make_agents(db_session, [make_dna(), make_dna()])
    engine = ShadowExecutionAdapter(FakeBook([book(bid=99.95, ask=100.05, depth=(100.0, 100.0, 100.0))]))
    c1 = make_context(1, 100.0, rsi=65.0)
    await cycle(db_session, engine, c1)
    orders = (await db_session.execute(select(Order))).scalars().all()
    assert len(orders) == 2 and {o.venue for o in orders} == {ExecutionVenue.SHADOW}
    assert all(o.raw_venue_response["sent_to_exchange"] is False and o.filled_price == pytest.approx(100.05) for o in orders)
    await cycle(db_session, engine, make_context(2, 101.0, rsi=30.0), c1)                 # exit signal
    trades = (await db_session.execute(select(Trade))).scalars().all()
    assert len(trades) == 2 and {t.stage for t in trades} == {StrategyStage.SHADOW}      # hypothetical PnL, SHADOW stage
    assert all(t.exit_price == pytest.approx(99.95) for t in trades)          # closing a long sells into the REAL bid
