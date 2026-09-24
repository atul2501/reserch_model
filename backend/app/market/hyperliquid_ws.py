"""Hyperliquid WebSocket market-data stream (spec phase 17).

Primary real-time candle feed; REST (`HyperliquidClient`) remains the source
for warm-up, backfill and reconciliation. This module is transport only —
connect, subscribe, heartbeat, validate, de-duplicate, order, reconnect. It
never decides what is "final": candles are handed to `on_candles` (normally
`MarketDataService.upsert_candles`) which applies the single finality rule.

Behaviour
  * connect + subscribe {"type":"candle","coin":..,"interval":..}
  * heartbeat: `{"method":"ping"}` every `ping_interval` (server drops idle
    connections after ~60s); a missing pong / silent stream past
    `stale_after` seconds forces a reconnect (stale detection)
  * reconnect with exponential backoff + jitter; re-subscribes every time
  * message validation (pydantic); wrong coin/interval and malformed payloads
    are counted and dropped, never propagated
  * exact duplicate frames dropped; updates for a bar that is more than one
    interval behind the newest are dropped as out-of-order (REST reconciles)
  * FUTURE-dated frames (open time beyond now + tolerance), impossible close times and stale
    frames (older than a few intervals) are dropped and must never advance ordering state, so
    one bogus far-future frame cannot make every later real frame look "out of order"
  * dedup/ordering state is recorded only AFTER the frame was delivered successfully, so an
    identical retry after a failed DB write is not swallowed
  * graceful `stop()`
"""
from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError, field_validator

from app.core import metrics
from app.core.logging import get_logger

logger = get_logger(__name__)

OnCandles = Callable[[list[dict]], Awaitable[None]]


class WsCandle(BaseModel):
    t: int
    T: int
    s: str
    i: str
    o: float
    h: float
    l: float
    c: float
    v: float
    n: int = 0

    @field_validator("o", "h", "l", "c", "v", mode="before")
    @classmethod
    def _numeric(cls, v):
        return float(v)

    def to_raw(self) -> dict:
        """The REST wire format MarketDataService.upsert_candles consumes."""
        return {"t": self.t, "T": self.T, "o": str(self.o), "h": str(self.h), "l": str(self.l),
                "c": str(self.c), "v": str(self.v), "n": self.n}

    def fingerprint(self) -> tuple:
        return (self.t, self.o, self.h, self.l, self.c, self.v, self.n)


@dataclass
class WsStats:
    connected: bool = False
    connects: int = 0
    reconnects: int = 0
    messages: int = 0
    candles_delivered: int = 0
    duplicates: int = 0
    invalid: int = 0
    out_of_order: int = 0
    pings_sent: int = 0
    stale_reconnects: int = 0
    future_frames: int = 0
    stale_frames: int = 0
    delivery_failures: int = 0
    pongs_received: int = 0
    last_pong_monotonic: float | None = None
    last_message_monotonic: float | None = None
    last_error: str | None = None
    newest_open_time: int | None = None
    recent: dict[int, tuple] = field(default_factory=dict)


class HyperliquidWebSocket:
    def __init__(
        self,
        url: str,
        coin: str,
        interval: str,
        on_candles: OnCandles,
        *,
        interval_ms: int = 60_000,
        connect: Callable[..., Any] | None = None,
        ping_interval: float = 30.0,
        stale_after: float = 90.0,
        backoff_min: float = 1.0,
        backoff_max: float = 30.0,
        future_tolerance_ms: int = 5_000,
        stale_frame_intervals: int = 3,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self._url, self._coin, self._interval = url, coin, interval
        self._on_candles = on_candles
        self._interval_ms = interval_ms
        if connect is None:
            import websockets
            connect = websockets.connect
        self._connect = connect
        self._ping_interval, self._stale_after = ping_interval, stale_after
        self._backoff_min, self._backoff_max = backoff_min, backoff_max
        self._future_tolerance_ms = future_tolerance_ms
        self._stale_frame_ms = stale_frame_intervals * interval_ms
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._stop = asyncio.Event()
        self.stats = WsStats()

    # -- public ------------------------------------------------------------ #
    @property
    def is_stale(self) -> bool:
        last = self.stats.last_message_monotonic
        return last is None or (time.monotonic() - last) > self._stale_after

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        """Connect/serve/reconnect until `stop()`. Never raises (except cancellation)."""
        attempt = 0
        while not self._stop.is_set():
            session = asyncio.create_task(self._session(), name="ws-session")
            stopper = asyncio.create_task(self._stop.wait())
            try:
                done, _ = await asyncio.wait({session, stopper}, return_when=asyncio.FIRST_COMPLETED)
            except asyncio.CancelledError:
                session.cancel()
                stopper.cancel()
                await asyncio.gather(session, stopper, return_exceptions=True)
                raise
            if session not in done:              # stop() requested mid-session: close promptly
                session.cancel()
                await asyncio.gather(session, return_exceptions=True)
                self.stats.connected = False
                break
            stopper.cancel()
            exc = session.exception()
            self.stats.connected = False
            if exc is None:
                attempt = 0 if self.stats.messages else attempt + 1
            else:
                self.stats.last_error = f"{type(exc).__name__}: {exc}"[:300]
                attempt += 1
                logger.warning("ws.session_error", error=self.stats.last_error, attempt=attempt)
            if self._stop.is_set():
                break
            self.stats.reconnects += 1
            metrics.inc("ws_reconnects")
            delay = min(self._backoff_max, self._backoff_min * (2 ** max(0, attempt - 1)))
            delay += random.uniform(0, delay * 0.25)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass

    # -- internals ---------------------------------------------------------- #
    async def _session(self) -> None:
        async with self._connect(self._url, ping_interval=None, close_timeout=2) as ws:
            self.stats.connected = True
            self.stats.connects += 1
            await ws.send(json.dumps({
                "method": "subscribe",
                "subscription": {"type": "candle", "coin": self._coin, "interval": self._interval},
            }))
            logger.info("ws.subscribed", coin=self._coin, interval=self._interval)
            self.stats.last_message_monotonic = time.monotonic()
            pinger = asyncio.create_task(self._heartbeat(ws))
            recv: asyncio.Future | None = None
            try:
                while not self._stop.is_set():
                    recv = asyncio.ensure_future(asyncio.wait_for(ws.recv(), timeout=self._stale_after))
                    await asyncio.wait({recv, pinger}, return_when=asyncio.FIRST_COMPLETED)
                    if pinger.done():
                        # A dead heartbeat means the connection is unhealthy: reconnect, never limp on.
                        recv.cancel()
                        await asyncio.gather(recv, return_exceptions=True)
                        exc = pinger.exception() if not pinger.cancelled() else None
                        metrics.inc("ws_heartbeat_failures")
                        raise ConnectionError(f"heartbeat failed: {exc!r}")
                    try:
                        raw = recv.result()
                    except asyncio.TimeoutError:
                        self.stats.stale_reconnects += 1
                        metrics.inc("ws_stale_reconnects")
                        logger.error("ws.stale_stream_reconnecting", silent_seconds=self._stale_after)
                        return
                    await self._handle(raw)
            finally:
                # A cancelled session (stop()/reconnect) must not leak the in-flight recv or the pinger.
                for task in (recv, pinger):
                    if task is not None and not task.done():
                        task.cancel()
                for task in (recv, pinger):
                    if task is not None:
                        try:
                            await task
                        except (asyncio.CancelledError, Exception):
                            pass

    async def _heartbeat(self, ws) -> None:
        while True:
            await asyncio.sleep(self._ping_interval)
            await ws.send(json.dumps({"method": "ping"}))
            self.stats.pings_sent += 1

    async def _handle(self, raw: str | bytes) -> None:
        self.stats.last_message_monotonic = time.monotonic()
        self.stats.messages += 1
        try:
            msg = json.loads(raw)
        except (TypeError, ValueError):
            self._invalid("non_json")
            return
        if not isinstance(msg, dict):
            self._invalid("not_object")
            return
        channel = msg.get("channel")
        if channel == "pong":
            self.stats.pongs_received += 1
            self.stats.last_pong_monotonic = time.monotonic()
            return
        if channel == "subscriptionResponse":
            return
        if channel != "candle":
            return
        data = msg.get("data")
        items = data if isinstance(data, list) else [data]
        deliver: list[dict] = []
        pending: list[tuple[int, tuple]] = []      # (open_time, fingerprint) recorded only after delivery
        now_ms = self._clock_ms()
        for item in items:
            try:
                candle = WsCandle.model_validate(item)
            except (ValidationError, TypeError):
                self._invalid("schema")
                continue
            if candle.s != self._coin or candle.i != self._interval:
                self._invalid("wrong_market")
                continue
            if candle.T < candle.t or candle.h < candle.l or candle.T - candle.t > self._interval_ms:
                self._invalid("inconsistent_ohlc")
                continue
            if candle.t > now_ms + self._future_tolerance_ms:
                # A bar that has not opened yet cannot exist. Dropped WITHOUT touching newest_open_time.
                self.stats.future_frames += 1
                metrics.inc("ws_future_frames")
                logger.error("ws.future_dated_frame_dropped", open_time=candle.t, now_ms=now_ms)
                continue
            if candle.t < now_ms - self._stale_frame_ms:
                self.stats.stale_frames += 1     # far behind the wall clock: history is REST's job
                metrics.inc("ws_stale_frames")
                continue
            fp = candle.fingerprint()
            if self.stats.recent.get(candle.t) == fp or (candle.t, fp) in pending:
                self.stats.duplicates += 1
                metrics.inc("ws_duplicates")
                continue
            newest = self.stats.newest_open_time
            if newest is not None and candle.t < newest - self._interval_ms:
                self.stats.out_of_order += 1
                metrics.inc("ws_out_of_order")
                continue
            pending.append((candle.t, fp))
            deliver.append(candle.to_raw())
        if deliver:
            try:
                await self._on_candles(deliver)
            except Exception as exc:  # a DB hiccup must not kill the stream
                self.stats.delivery_failures += 1
                metrics.inc("ws_delivery_failures")
                logger.error("ws.on_candles_failed", error=str(exc))
                return  # nothing recorded: an identical retry frame is processed, not swallowed as a duplicate
            self.stats.candles_delivered += len(deliver)
            for open_time, fp in pending:
                self.stats.recent[open_time] = fp
                if self.stats.newest_open_time is None or open_time > self.stats.newest_open_time:
                    self.stats.newest_open_time = open_time
            if len(self.stats.recent) > 16:
                for old in sorted(self.stats.recent)[:-8]:
                    self.stats.recent.pop(old, None)

    def _invalid(self, reason: str) -> None:
        self.stats.invalid += 1
        metrics.inc("ws_invalid_messages", reason=reason)
