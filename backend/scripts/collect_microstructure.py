"""Real-time market-microstructure recorder (research data; separate process; never touches the trading DB).

Subscribes to Hyperliquid PUBLIC WebSocket channels and appends every message, stamped with local receipt time, to
hourly gzip JSON-lines files:

    <out>/<YYYYMMDD>/<coin>_<channel>_<YYYYMMDDHH>.jsonl.gz      one line: {"recv_ms": ..., "data": <channel payload>}

Channels (all real-time; nothing that only exists historically):
    trades  SOL, BTC   price, size, aggressor side ("B" buyer-initiated / "A" seller-initiated), exchange time
    bbo     SOL, BTC   best bid/offer with sizes, exchange time
    l2Book  SOL        top-of-book depth snapshots (exchange-paced), exchange time

Usage:  python -m scripts.collect_microstructure [--out data/microstructure] [--minutes 0 (=forever)]
Sends ONLY {"method": "subscribe"} and {"method": "ping"} messages. No orders, no keys, no signing.
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import random
import signal
import time
from datetime import datetime, timezone
from pathlib import Path

import websockets

from app.core.config import BACKEND_DIR, get_settings
from app.core.logging import configure_logging, get_logger

logger = get_logger(__name__)
SUBSCRIPTIONS = (
    {"type": "trades", "coin": "SOL"}, {"type": "trades", "coin": "BTC"},
    {"type": "bbo", "coin": "SOL"}, {"type": "bbo", "coin": "BTC"},
    {"type": "l2Book", "coin": "SOL"},
)
FLUSH_EVERY_S = 5.0


def coin_of(channel: str, data) -> str | None:
    if channel == "trades" and isinstance(data, list) and data:
        return data[0].get("coin")
    if isinstance(data, dict):
        return data.get("coin")
    return None


class HourlyWriter:
    def __init__(self, root: Path) -> None:
        self.root, self.files, self.counts = root, {}, {}

    def write(self, coin: str, channel: str, recv_ms: int, data) -> None:
        dt = datetime.fromtimestamp(recv_ms / 1000, tz=timezone.utc)
        key = (coin, channel, dt.strftime("%Y%m%d%H"))
        fh = self.files.get(key)
        if fh is None:
            for k in [k for k in self.files if k[2] != key[2]]:      # close the previous hour's files
                self.files.pop(k).close()
            d = self.root / dt.strftime("%Y%m%d")
            d.mkdir(parents=True, exist_ok=True)
            fh = self.files[key] = gzip.open(d / f"{coin}_{channel}_{key[2]}.jsonl.gz", "at", encoding="utf-8")
        fh.write(json.dumps({"recv_ms": recv_ms, "data": data}, separators=(",", ":")) + "\n")
        self.counts[(coin, channel)] = self.counts.get((coin, channel), 0) + 1

    def flush(self) -> None:
        for fh in self.files.values():
            fh.flush()

    def close(self) -> None:
        for fh in self.files.values():
            fh.close()
        self.files.clear()


def handle_message(raw: str, writer: HourlyWriter, recv_ms: int) -> bool:
    try:
        msg = json.loads(raw)
    except ValueError:
        return False
    ch = msg.get("channel") if isinstance(msg, dict) else None
    if ch not in ("trades", "bbo", "l2Book"):
        return False                                   # subscriptionResponse, pong, ...
    data = msg.get("data")
    coin = coin_of(ch, data)
    if coin is None:
        return False
    if ch == "trades":                                  # wallet addresses / tx hashes are not research inputs
        data = [{k: v for k, v in t.items() if k not in ("users", "hash")} for t in data]
    writer.write(coin, ch, recv_ms, data)
    return True


async def run(out: Path, stop: asyncio.Event, url: str) -> None:
    writer = HourlyWriter(out)
    attempt = 0
    last_flush = time.monotonic()
    try:
        while not stop.is_set():
            try:
                async with websockets.connect(url, ping_interval=None, close_timeout=2, max_size=2**22) as ws:
                    for sub in SUBSCRIPTIONS:
                        await ws.send(json.dumps({"method": "subscribe", "subscription": sub}))
                    logger.info("micro.subscribed", subscriptions=len(SUBSCRIPTIONS))
                    attempt, last_ping = 0, time.monotonic()
                    while not stop.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=30)
                        except asyncio.TimeoutError:
                            raise ConnectionError("stream silent for 30 s")
                        handle_message(raw, writer, time.time_ns() // 1_000_000)
                        now = time.monotonic()
                        if now - last_ping > 20:
                            await ws.send(json.dumps({"method": "ping"}))
                            last_ping = now
                        if now - last_flush > FLUSH_EVERY_S:
                            writer.flush()
                            last_flush = now
            except (OSError, ConnectionError, websockets.WebSocketException) as exc:
                attempt += 1
                delay = min(60.0, 2 ** min(attempt, 6)) * (1 + random.random() * 0.25)
                logger.warning("micro.reconnecting", error=str(exc)[:200], attempt=attempt, delay=round(delay, 1))
                try:
                    await asyncio.wait_for(stop.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
    finally:
        writer.close()
        logger.info("micro.stopped", counts={f"{c}:{ch}": n for (c, ch), n in writer.counts.items()})


async def main() -> None:
    configure_logging()
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/microstructure")
    ap.add_argument("--minutes", type=float, default=0.0, help="stop after N minutes (0 = run until signalled)")
    a = ap.parse_args()
    out = Path(a.out) if Path(a.out).is_absolute() else BACKEND_DIR / a.out
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:      # Windows: Ctrl+C raises KeyboardInterrupt instead
            pass
    if a.minutes > 0:
        loop.call_later(a.minutes * 60, stop.set)
    await run(out, stop, get_settings().hyperliquid_ws_url)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
