"""Paper execution realism (spec phase 7): slippage, fees, latency, partial
fills, rejects, lot size, determinism — and never any network I/O."""
from __future__ import annotations

import httpx
import pytest

from app.core.config import get_settings
from app.execution.base import ExecutionRequest
from app.execution import paper_adapter as pa
from app.models.enums import OrderStatus, Side


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    pa._SEEN_ORDER_IDS.clear()
    s = get_settings()
    monkeypatch.setattr(s, "paper_latency_jitter_ms", 0)
    monkeypatch.setattr(s, "paper_slippage_impact_bps_per_10k", 0.0)
    monkeypatch.setattr(s, "paper_partial_fill_probability", 0.0)
    monkeypatch.setattr(s, "paper_reject_probability", 0.0)
    monkeypatch.setattr(s, "paper_min_order_notional", 0.0)
    return s


def _req(cid="o1", side=Side.LONG, qty=1.0, price=100.0, **kw):
    return ExecutionRequest(client_order_id=cid, agent_id="a", symbol="SOL", side=side, quantity=qty, leverage=1.0, reference_price=price, **kw)


async def test_entry_slippage_is_adverse_for_both_sides():
    a = pa.PaperExecutionAdapter()
    long_fill = await a.submit_order(_req("l", Side.LONG))
    short_fill = await a.submit_order(_req("s", Side.SHORT))
    assert long_fill.filled_price > 100.0      # buying pays up
    assert short_fill.filled_price < 100.0     # shorting receives less


async def test_exit_slippage_is_adverse_too():
    a = pa.PaperExecutionAdapter()
    close_long = await a.submit_order(_req("x1", Side.LONG, reduce_only=True))     # selling to close a long
    close_short = await a.submit_order(_req("x2", Side.SHORT, reduce_only=True))   # buying to cover a short
    assert close_long.filled_price < 100.0
    assert close_short.filled_price > 100.0


async def test_stop_and_liquidation_slip_more_than_market_and_tp_limit_pays_none(_fresh):
    a = pa.PaperExecutionAdapter()
    market = await a.submit_order(_req("m", Side.LONG, reduce_only=True))
    stop = await a.submit_order(_req("st", Side.LONG, reduce_only=True, order_kind="stop"))
    liq = await a.submit_order(_req("lq", Side.LONG, reduce_only=True, order_kind="liquidation"))
    tp = await a.submit_order(_req("tp", Side.LONG, reduce_only=True, order_kind="take_profit"))
    assert abs(stop.filled_price - 100) > abs(market.filled_price - 100)
    assert abs(liq.filled_price - 100) >= abs(stop.filled_price - 100)
    assert tp.filled_price == pytest.approx(100.0)                         # resting limit: no slippage
    assert tp.fee == pytest.approx(100.0 * _fresh.paper_maker_fee_rate)   # maker fee
    assert market.fee == pytest.approx(market.filled_price * _fresh.paper_fee_rate)


async def test_size_aware_impact_increases_slippage(monkeypatch, _fresh):
    monkeypatch.setattr(_fresh, "paper_slippage_impact_bps_per_10k", 5.0)
    a = pa.PaperExecutionAdapter()
    small = await a.submit_order(_req("small", qty=1.0))
    big = await a.submit_order(_req("big", qty=1000.0))   # $100k
    assert (big.filled_price - 100) > (small.filled_price - 100)


async def test_fee_is_charged_on_filled_notional():
    a = pa.PaperExecutionAdapter()
    r = await a.submit_order(_req("f", qty=2.0))
    assert r.fee == pytest.approx(r.filled_price * r.filled_quantity * get_settings().paper_fee_rate)
    assert r.slippage_cost == pytest.approx(abs(r.filled_price - 100.0) * r.filled_quantity)


async def test_quantity_floored_to_lot_size_but_exits_never_rounded():
    a = pa.PaperExecutionAdapter()
    entry = await a.submit_order(_req("e", qty=0.0349))
    assert entry.filled_quantity == pytest.approx(0.03)
    tiny_exit = await a.submit_order(_req("t", qty=0.0031, reduce_only=True))
    assert tiny_exit.filled_quantity == pytest.approx(0.0031)          # dust position can always be closed
    dust_entry = await a.submit_order(_req("d", qty=0.004))
    assert dust_entry.status == OrderStatus.FAILED and dust_entry.rejection_reason == "quantity_below_lot_size"


async def test_min_notional_rejects_entries_not_exits(monkeypatch, _fresh):
    monkeypatch.setattr(_fresh, "paper_min_order_notional", 10.0)
    a = pa.PaperExecutionAdapter()
    entry = await a.submit_order(_req("small", qty=0.05, price=100.0))      # $5
    assert entry.status == OrderStatus.FAILED and entry.rejection_reason == "below_min_order_notional"
    exit_ = await a.submit_order(_req("smallx", qty=0.05, price=100.0, reduce_only=True))
    assert exit_.status == OrderStatus.FILLED


async def test_partial_fills_when_configured_never_on_exits(monkeypatch, _fresh):
    monkeypatch.setattr(_fresh, "paper_partial_fill_probability", 1.0)
    monkeypatch.setattr(_fresh, "paper_partial_fill_min_fraction", 0.4)
    a = pa.PaperExecutionAdapter()
    r = await a.submit_order(_req("p", qty=10.0))
    assert r.status == OrderStatus.PARTIALLY_FILLED and 4.0 <= r.filled_quantity < 10.0
    e = await a.submit_order(_req("px", qty=10.0, reduce_only=True))
    assert e.status == OrderStatus.FILLED and e.filled_quantity == pytest.approx(10.0)


async def test_random_rejects_apply_to_entries_only(monkeypatch, _fresh):
    monkeypatch.setattr(_fresh, "paper_reject_probability", 1.0)
    a = pa.PaperExecutionAdapter()
    r = await a.submit_order(_req("rej", qty=1.0))
    assert r.status == OrderStatus.FAILED and r.rejection_reason == "simulated_exchange_reject"
    assert (await a.submit_order(_req("rejx", qty=1.0, reduce_only=True))).status == OrderStatus.FILLED


async def test_fills_are_deterministic_per_order_id_and_independent_of_order_of_arrival(monkeypatch, _fresh):
    monkeypatch.setattr(_fresh, "paper_partial_fill_probability", 0.5)
    monkeypatch.setattr(_fresh, "paper_latency_jitter_ms", 40)
    a = pa.PaperExecutionAdapter()
    first = [await a.submit_order(_req(f"id{i}", qty=5.0)) for i in range(6)]
    pa._SEEN_ORDER_IDS.clear()
    second = [await a.submit_order(_req(f"id{i}", qty=5.0)) for i in reversed(range(6))][::-1]
    assert [(r.filled_quantity, r.latency_ms, round(r.filled_price, 9)) for r in first] == \
           [(r.filled_quantity, r.latency_ms, round(r.filled_price, 9)) for r in second]


async def test_latency_is_reported_without_sleeping(monkeypatch):
    import asyncio, time
    def _boom(*a, **k):
        raise AssertionError("paper adapter must not sleep unless paper_simulate_latency_sleep is set")
    monkeypatch.setattr(asyncio, "sleep", _boom)
    a = pa.PaperExecutionAdapter()
    t0 = time.monotonic()
    r = await a.submit_order(_req("lat"))
    assert r.latency_ms == get_settings().paper_latency_ms and time.monotonic() - t0 < 0.5


async def test_idempotent_on_client_order_id():
    a = pa.PaperExecutionAdapter()
    assert (await a.submit_order(_req("dup"))).status == OrderStatus.FILLED
    again = await a.submit_order(_req("dup"))
    assert again.status == OrderStatus.FAILED and again.rejection_reason == "duplicate_client_order_id"


async def test_paper_and_shadow_adapters_never_touch_the_network(monkeypatch):
    def _no_net(*a, **k):
        raise AssertionError("paper execution must never perform network I/O")
    for name in ("request", "get", "post", "send"):
        monkeypatch.setattr(httpx.AsyncClient, name, _no_net)
    monkeypatch.setattr(httpx.Client, "send", _no_net)
    import socket
    monkeypatch.setattr(socket.socket, "connect", _no_net)
    r = await pa.PaperExecutionAdapter().submit_order(_req("net"))
    assert r.status == OrderStatus.FILLED
