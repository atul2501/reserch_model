"""Hyperliquid WebSocket transport (spec phase 17) against an in-process fake server."""
from __future__ import annotations

import asyncio
import json

import pytest
import websockets

from app.market.hyperliquid_ws import HyperliquidWebSocket


def candle(t, c=100.0, v=10.0, coin="SOL", interval="1m", **kw):
    d = {"t": t, "T": t + 59_999, "s": coin, "i": interval, "o": "100", "c": str(c), "h": "101", "l": "99", "v": str(v), "n": 5}
    d.update(kw)
    return {"channel": "candle", "data": d}


class FakeServer:
    """Scriptable exchange: every accepted connection runs `script(ws, conn_index)`."""

    def __init__(self, script):
        self.script, self.received, self.connections = script, [], 0
        self.server = None
        self.url = None

    async def _handler(self, ws):
        idx = self.connections
        self.connections += 1
        async def reader():
            try:
                async for m in ws:
                    self.received.append(json.loads(m))
            except Exception:
                pass
        rd = asyncio.create_task(reader())
        try:
            await self.script(ws, idx)
        finally:
            rd.cancel()

    async def __aenter__(self):
        self.server = await websockets.serve(self._handler, "127.0.0.1", 0)
        port = self.server.sockets[0].getsockname()[1]
        self.url = f"ws://127.0.0.1:{port}"
        return self

    async def __aexit__(self, *a):
        self.server.close()
        await self.server.wait_closed()


async def _run_until(client, cond, timeout=5.0):
    task = asyncio.create_task(client.run())
    try:
        end = asyncio.get_event_loop().time() + timeout
        while not cond():
            if asyncio.get_event_loop().time() > end:
                raise AssertionError("condition not met in time")
            await asyncio.sleep(0.02)
    finally:
        client.stop()
        await asyncio.wait_for(task, 5)


def make(url, sink, **kw):
    async def on(raws):
        sink.extend(raws)
    kw.setdefault("backoff_min", 0.05); kw.setdefault("backoff_max", 0.2)
    return HyperliquidWebSocket(url, "SOL", "1m", on, **kw)


async def test_subscribes_receives_validates_and_delivers():
    got = []

    async def script(ws, idx):
        await ws.send(json.dumps({"channel": "subscriptionResponse", "data": {}}))
        await ws.send(json.dumps(candle(60_000)))
        await ws.send(json.dumps([1, 2]))                       # not an object -> invalid
        await ws.send("garbage{")                                # not json -> invalid
        await ws.send(json.dumps(candle(120_000, coin="BTC")))  # wrong market -> invalid
        await ws.send(json.dumps(candle(120_000, h=1, l=5) if False else {"channel": "candle", "data": {"t": 1}}))  # schema -> invalid
        await ws.send(json.dumps(candle(120_000, c=101)))
        await asyncio.sleep(5)

    async with FakeServer(script) as srv:
        client = make(srv.url, got)
        await _run_until(client, lambda: len(got) == 2)
        sub = srv.received[0]
        assert sub == {"method": "subscribe", "subscription": {"type": "candle", "coin": "SOL", "interval": "1m"}}
    assert [g["t"] for g in got] == [60_000, 120_000]
    assert client.stats.invalid >= 4 and client.stats.connects == 1


async def test_exact_duplicates_dropped_but_updates_to_the_open_bar_pass():
    got = []

    async def script(ws, idx):
        await ws.send(json.dumps(candle(60_000, c=100.5)))
        await ws.send(json.dumps(candle(60_000, c=100.5)))     # exact dup
        await ws.send(json.dumps(candle(60_000, c=100.9)))     # same bar, updated -> genuine update
        await asyncio.sleep(5)

    async with FakeServer(script) as srv:
        client = make(srv.url, got)
        await _run_until(client, lambda: len(got) == 2)
    assert [g["c"] for g in got] == ["100.5", "100.9"] and client.stats.duplicates == 1


async def test_out_of_order_old_bars_are_dropped():
    got = []

    async def script(ws, idx):
        await ws.send(json.dumps(candle(600_000)))
        await ws.send(json.dumps(candle(540_000, c=99)))       # previous bar update: allowed
        await ws.send(json.dumps(candle(300_000, c=98)))       # 5 bars behind: dropped
        await asyncio.sleep(5)

    async with FakeServer(script) as srv:
        client = make(srv.url, got)
        await _run_until(client, lambda: len(got) == 2)
        await asyncio.sleep(0.1)
    assert [g["t"] for g in got] == [600_000, 540_000] and client.stats.out_of_order == 1


async def test_reconnects_with_backoff_and_resubscribes_after_server_drop():
    got = []

    async def script(ws, idx):
        await ws.send(json.dumps(candle(60_000 * (idx + 1))))
        if idx == 0:
            await ws.close()          # server drops the first connection
            return
        await asyncio.sleep(5)

    async with FakeServer(script) as srv:
        client = make(srv.url, got)
        await _run_until(client, lambda: len(got) >= 2)
        subs = [m for m in srv.received if m.get("method") == "subscribe"]
    assert srv.connections >= 2 and len(subs) >= 2         # re-subscribed on the new connection
    assert client.stats.reconnects >= 1 and client.stats.connects >= 2


async def test_client_survives_connection_refused_then_connects():
    got = []
    port_holder = {}

    async def script(ws, idx):
        await ws.send(json.dumps(candle(60_000)))
        await asyncio.sleep(5)

    async with FakeServer(script) as srv:
        real_connect = websockets.connect
        attempts = {"n": 0}

        def flaky(url, **kw):
            attempts["n"] += 1
            if attempts["n"] <= 2:
                raise ConnectionRefusedError("down")
            return real_connect(url, **kw)

        client = make(srv.url, got, connect=flaky)
        await _run_until(client, lambda: len(got) == 1)
    assert attempts["n"] >= 3 and client.stats.reconnects >= 2 and client.stats.connects >= 1


async def test_heartbeat_pings_are_sent():
    async def script(ws, idx):
        await asyncio.sleep(5)

    async with FakeServer(script) as srv:
        client = make(srv.url, [], ping_interval=0.05)
        await _run_until(client, lambda: client.stats.pings_sent >= 2)
        assert {"method": "ping"} in srv.received


async def test_silent_stream_is_detected_stale_and_reconnected():
    async def script(ws, idx):
        if idx == 0:
            await asyncio.sleep(5)                 # connected but never sends anything
        else:
            await ws.send(json.dumps(candle(60_000)))
            await asyncio.sleep(5)

    got = []
    async with FakeServer(script) as srv:
        client = make(srv.url, got, stale_after=0.2)
        await _run_until(client, lambda: len(got) == 1)
    assert client.stats.stale_reconnects >= 1 and srv.connections >= 2


async def test_graceful_shutdown_returns_promptly():
    async def script(ws, idx):
        await asyncio.sleep(30)

    async with FakeServer(script) as srv:
        client = make(srv.url, [])
        task = asyncio.create_task(client.run())
        await asyncio.sleep(0.2)
        client.stop()
        await asyncio.wait_for(task, 5)
        assert client.stats.connected is False


async def test_callback_failure_does_not_kill_the_stream():
    seen = []

    async def bad(raws):
        seen.append(raws)
        raise RuntimeError("db down")

    async def script(ws, idx):
        await ws.send(json.dumps(candle(60_000)))
        await ws.send(json.dumps(candle(120_000)))
        await asyncio.sleep(5)

    async with FakeServer(script) as srv:
        client = HyperliquidWebSocket(srv.url, "SOL", "1m", bad, backoff_min=0.05)
        await _run_until(client, lambda: len(seen) == 2)
    assert client.stats.connects == 1
