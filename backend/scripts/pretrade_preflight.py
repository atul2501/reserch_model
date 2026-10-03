"""Pre-flight checks before the 2-week PRETRADE_MODE=shadow run (run ON the EC2 host, in the worker's environment).

    python -m scripts.pretrade_preflight [--backup-dir /path/to/pg_dumps] [--days 14]

Checks (PASS / WARN / FAIL; exit code 1 if any FAIL):
   1 clock sync          SNTP offset vs pool.ntp.org AND exchange-time lag of the live WebSocket BBO
   2 database backup     newest *.dump / *.sql(.gz) in --backup-dir is < 26 h old and non-empty
   3 shadow mode         TRADING_MODE=paper, PRETRADE_MODE=shadow, PRETRADE_MODE=on impossible
   4 no live orders      live gates closed, execution engine is PAPER
   5 no balance writes   the shadow's read-only transaction REFUSES an UPDATE on the real database
   6 shadow directory    writable; free disk >= 2 x the estimated 14-day volume
   7 logging             level / JSON logging configured
   8 council / Ollama    reported (enabled, cadence, model, key COUNT only) - a deliberate operator decision
   9 order-book source   REST l2Book snapshot lag vs WebSocket BBO lag (use the fresher one)
  10 microstructure dir  writable (collector output)
Read-only except for creating+deleting one probe file in each output directory.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import socket
import statistics
import struct
import time
from pathlib import Path

from app.core.config import BACKEND_DIR, get_settings

RESULTS: list[dict] = []


def report(n: int, name: str, status: str, detail: str) -> None:
    RESULTS.append({"check": n, "name": name, "status": status, "detail": detail})


def sntp_offset_ms(server: str = "pool.ntp.org", timeout: float = 3.0) -> float | None:
    """Clock offset (server - local) in ms from one SNTP query; None if unreachable."""
    try:
        pkt = b"\x1b" + 47 * b"\0"
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(timeout)
            t0 = time.time()
            s.sendto(pkt, (server, 123))
            data, _ = s.recvfrom(48)
            t3 = time.time()
        secs, frac = struct.unpack("!II", data[40:48])
        server_t = secs - 2208988800 + frac / 2**32
        return (server_t - (t0 + t3) / 2) * 1000
    except OSError:
        return None


async def ws_bbo_lag_ms(url: str, seconds: float = 8.0) -> list[float]:
    import websockets
    lags = []
    try:
        async with websockets.connect(url, ping_interval=None, close_timeout=2) as ws:
            await ws.send(json.dumps({"method": "subscribe", "subscription": {"type": "bbo", "coin": "SOL"}}))
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                try:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=max(0.1, end - time.monotonic())))
                except asyncio.TimeoutError:
                    break
                if msg.get("channel") == "bbo":
                    lags.append(time.time_ns() // 1_000_000 - int(msg["data"]["time"]))
    except Exception:  # noqa: BLE001
        pass
    return lags


async def rest_book_lag_ms(n: int = 5) -> list[float]:
    from app.market.hyperliquid_client import HyperliquidClient
    c = HyperliquidClient(timeout=5)
    lags = []
    try:
        for _ in range(n):
            raw = await c.get_l2_book("SOL")
            lags.append(time.time_ns() // 1_000_000 - int(raw.get("time", 0)))
            await asyncio.sleep(0.5)
    except Exception:  # noqa: BLE001
        pass
    finally:
        await c.aclose()
    return lags


def _dir(p: str) -> Path:
    q = Path(p)
    return q if q.is_absolute() else BACKEND_DIR / q


def _writable(d: Path) -> bool:
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".preflight_probe"
        probe.write_text("ok"); probe.unlink()
        return True
    except OSError:
        return False


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backup-dir", default=None)
    ap.add_argument("--days", type=float, default=14.0)
    a = ap.parse_args()
    s = get_settings()

    # 1 clock
    off = sntp_offset_ms()
    lags = await ws_bbo_lag_ms(s.hyperliquid_ws_url)
    ws_p50 = statistics.median(lags) if lags else None
    ok_clock = (off is not None and abs(off) < 100) or (off is None and ws_p50 is not None and 0 <= ws_p50 < 1000)
    report(1, "clock sync", "PASS" if ok_clock else "FAIL",
           f"SNTP offset {('%.1f ms' % off) if off is not None else 'unavailable'}; WS BBO exchange->receipt lag p50 "
           f"{('%.0f ms' % ws_p50) if ws_p50 is not None else 'unavailable'} (n={len(lags)}). Negative lag = local clock behind.")

    # 2 backup
    if a.backup_dir:
        files = [p for p in Path(a.backup_dir).glob("*") if p.suffix in (".dump", ".sql", ".gz") and p.is_file()]
        newest = max(files, key=lambda p: p.stat().st_mtime) if files else None
        if newest is None:
            report(2, "database backup", "FAIL", f"no *.dump/*.sql/*.gz in {a.backup_dir}")
        else:
            age_h = (time.time() - newest.stat().st_mtime) / 3600
            report(2, "database backup", "PASS" if age_h < 26 and newest.stat().st_size > 0 else "FAIL",
                   f"{newest.name}: {newest.stat().st_size / 1e6:.1f} MB, {age_h:.1f} h old")
    else:
        report(2, "database backup", "FAIL", "pass --backup-dir <dir with pg_dump files>; a fresh backup is required before the run")

    # 3 / 4 modes and live gates
    tm = getattr(s.trading_mode, "value", s.trading_mode)
    report(3, "shadow mode", "PASS" if tm == "paper" and s.pretrade_mode == "shadow" else "FAIL",
           f"TRADING_MODE={tm}, PRETRADE_MODE={s.pretrade_mode} (PRETRADE_MODE=on is refused by Settings validation)")
    from app.execution.router import get_execution_engine
    try:
        venue = getattr(get_execution_engine(s).venue, "value", None)
    except Exception as exc:  # noqa: BLE001
        venue = f"error: {exc}"
    live_closed = not s.is_live() and not s.live_trading_enabled
    report(4, "no live orders", "PASS" if live_closed and venue == "PAPER" else "FAIL",
           f"is_live={s.is_live()}, LIVE_TRADING_ENABLED={s.live_trading_enabled}, execution venue={venue}")

    # 5 read-only shadow transaction against the REAL database
    try:
        from sqlalchemy import text
        from app.core.database import engine
        from app.pretrade.shadow import read_only_session
        refused = False
        async with read_only_session(engine) as sess:
            try:
                await sess.execute(text("UPDATE agents SET balance = balance WHERE false"))
            except Exception as exc:  # noqa: BLE001
                refused = "read-only" in str(exc).lower() or "readonly" in str(exc).lower()
        report(5, "no balance writes", "PASS" if refused else "FAIL",
               "the shadow transaction REFUSED an UPDATE on agents (DB-enforced read-only)" if refused
               else "the shadow transaction did NOT refuse a write - do not start the run")
    except Exception as exc:  # noqa: BLE001
        report(5, "no balance writes", "FAIL", f"could not test against the database: {type(exc).__name__}: {exc}")

    # 6 shadow dir + disk
    sd = _dir(s.pretrade_shadow_dir)
    existing = sum(f.stat().st_size for f in sd.glob("pretrade_shadow_*.jsonl")) if sd.exists() else 0
    days_have = len(list(sd.glob("pretrade_shadow_*.jsonl"))) if sd.exists() else 0
    per_day = (existing / days_have) if days_have else 150e6          # ~1,980 records/41 min -> ~150 MB/day uncompressed
    need = per_day * a.days * 2
    free = shutil.disk_usage(sd if sd.exists() else BACKEND_DIR).free
    report(6, "shadow directory", "PASS" if _writable(sd) and free > need else "FAIL",
           f"{sd} writable={_writable(sd)}; free {free / 1e9:.1f} GB vs 2 x estimated {a.days:g}-day volume {need / 1e9:.1f} GB")

    # 7 logging
    report(7, "logging", "PASS", f"LOG_LEVEL={s.log_level}, LOG_JSON={s.log_json} (shadow failures log 'pretrade_shadow.cycle_failed')")

    # 8 council
    keys = len(s.ollama_api_key_list)
    report(8, "council / Ollama", "WARN" if s.council_enabled else "PASS",
           f"COUNCIL_ENABLED={s.council_enabled}, every {s.council_interval_candles} candles, model={s.ollama_model}, "
           f"{keys} API key(s). Shadow only RECORDS the council; with it enabled the existing paper path still waits for it. "
           "Decide deliberately (production keys + rate limits).")

    # 9 order book
    rl = await rest_book_lag_ms()
    rest_p50 = statistics.median(rl) if rl else None
    better = "WebSocket BBO" if (ws_p50 is not None and (rest_p50 is None or ws_p50 < rest_p50)) else "REST l2Book"
    report(9, "order-book source", "PASS" if (rest_p50 is not None and rest_p50 < 1000) else "WARN",
           f"REST l2Book lag p50 {rest_p50 if rest_p50 is not None else 'n/a'} ms; WS BBO lag p50 {ws_p50 if ws_p50 is not None else 'n/a'} ms. "
           f"Fresher source here: {better}. The shadow path reads REST l2Book; treat its timestamp as authoritative only if this is < 1 s.")

    # 10 microstructure dir
    md = _dir(s.microstructure_dir)
    report(10, "microstructure directory", "PASS" if _writable(md) else "FAIL",
           f"{md} writable={_writable(md)} (run: python -m scripts.collect_microstructure as its own service)")

    width = max(len(r["name"]) for r in RESULTS)
    for r in RESULTS:
        print(f"{r['check']:>2}. {r['name']:<{width}}  {r['status']:<4}  {r['detail']}")
    fails = [r for r in RESULTS if r["status"] == "FAIL"]
    print(f"\n{'NOT READY' if fails else 'READY FOR SHADOW RUN'}: {len(fails)} FAIL, "
          f"{sum(r['status'] == 'WARN' for r in RESULTS)} WARN")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
