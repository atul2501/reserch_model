"""Publish / read process runtime status through the database so the API
process can report on the worker process (spec phases 36, 37)."""
from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.system_flags import active_flags
from app.models.market import MarketCandle
from app.models.system import SystemStatus, WorkerCycle, WorkerLease

WORKER = "worker"


async def publish_status(db: AsyncSession, name: str, payload: dict) -> None:
    row = await db.get(SystemStatus, name)
    payload = {**payload, "published_at": time.time()}
    if row is None:
        db.add(SystemStatus(name=name, payload=payload))
    else:
        row.payload = payload
    await db.commit()


async def read_status(db: AsyncSession, name: str) -> dict | None:
    row = await db.get(SystemStatus, name)
    return row.payload if row else None


def _age(ts: float | None, now: float) -> float | None:
    return None if ts is None else max(0.0, now - ts)


async def compute_system_status(db: AsyncSession) -> dict:
    """One consolidated health picture. Components: database, worker, market
    data, hyperliquid (stream), ollama, council. Each has `status` in
    {ok, degraded, down, unknown} and the facts behind it."""
    s = get_settings()
    now = time.time()
    out: dict = {"now": now, "trading_mode": s.trading_mode.value}

    # ---- database -------------------------------------------------------------- #
    try:
        await db.execute(select(1))
        out["database"] = {"status": "ok", "dialect": db.get_bind().dialect.name}
    except Exception as exc:
        out["database"] = {"status": "down", "error": type(exc).__name__}
        out["overall"] = "down"
        return out

    # ---- worker ---------------------------------------------------------------- #
    lease = await db.get(WorkerLease, "decision-worker")
    last_cycle = (
        await db.execute(select(WorkerCycle).order_by(WorkerCycle.candle_timestamp.desc()).limit(1))
    ).scalar_one_or_none()
    hb_age = _age(lease.heartbeat_at if lease else None, now)
    hb_limit = max(2.5 * s.worker_lease_heartbeat_seconds, 90.0)
    cycle_age = _age(last_cycle.cycle_completed_at if last_cycle else None, now)
    interval_s = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}.get(s.market_timeframe, 60)
    if lease is None or hb_age is None:
        w_status = "unknown"
    elif hb_age > hb_limit or lease.expires_at < now:
        w_status = "down"
    elif cycle_age is not None and cycle_age > 3 * interval_s + 30:
        w_status = "degraded"
    else:
        w_status = "ok"
    out["worker"] = {
        "status": w_status, "heartbeat_age_seconds": hb_age, "lease_owner": lease.owner_id if lease else None,
        "lease_epoch": lease.epoch if lease else None,
        "last_cycle": None if last_cycle is None else {
            "cycle_id": last_cycle.cycle_id, "candle_open_time": last_cycle.candle_timestamp, "status": last_cycle.status,
            "attempts": last_cycle.attempts, "latency_seconds": last_cycle.cycle_latency_seconds,
            "completed_age_seconds": cycle_age, "council_status": last_cycle.council_status,
            "agents_processed": last_cycle.agents_processed, "halt_reason": last_cycle.trading_halt_reason,
            "error": last_cycle.error,
        },
    }

    # ---- market data ------------------------------------------------------------ #
    last_confirmed = (
        await db.execute(
            select(MarketCandle).where(MarketCandle.symbol == s.market_symbol, MarketCandle.timeframe == s.market_timeframe,
                                       MarketCandle.is_final.is_(True)).order_by(MarketCandle.open_time.desc()).limit(1)
        )
    ).scalar_one_or_none()
    data_age = None if last_confirmed is None else max(0.0, now - last_confirmed.close_time / 1000)
    flags = await active_flags(db)
    if last_confirmed is None or data_age is None:
        m_status = "unknown"
    elif data_age > s.data_stale_threshold_seconds or "data_gap_halt" in flags:
        m_status = "down"
    elif data_age > 2 * interval_s + 10:
        m_status = "degraded"
    else:
        m_status = "ok"
    out["market_data"] = {
        "status": m_status, "symbol": s.market_symbol, "timeframe": s.market_timeframe,
        "last_confirmed_candle_open_time": last_confirmed.open_time if last_confirmed else None,
        "freshness_seconds": data_age, "data_gap_halt": "data_gap_halt" in flags,
    }
    out["flags"] = flags

    # ---- worker-published runtime (ollama / websocket / metrics) --------------------- #
    payload = await read_status(db, WORKER) or {}
    pub_age = _age(payload.get("published_at"), now)
    ws = payload.get("websocket")
    if ws is None:
        h_status = "unknown"
    elif ws.get("connected") and not ws.get("stale"):
        h_status = "ok"
    elif m_status == "ok":
        h_status = "degraded"  # stream down but REST fallback is keeping data fresh
    else:
        h_status = "down"
    out["hyperliquid"] = {"status": h_status, "websocket": ws, "rest_fallback": m_status == "ok"}

    keys = payload.get("ollama_keys")
    if keys is None:
        o_status = "unknown"
    elif keys and all(k["status"] == "unhealthy" for k in keys):
        o_status = "down"
    elif any(k["status"] != "healthy" for k in keys):
        o_status = "degraded"
    else:
        o_status = "ok"
    out["ollama"] = {"status": o_status, "keys": keys, "configured": bool(s.ollama_base_url and s.ollama_model)}

    last_council = payload.get("last_council")
    out["council"] = last_council or {"status": "unknown"}
    out["runtime_snapshot_age_seconds"] = pub_age

    # A worker that has never published a heartbeat is NOT healthy: nothing is trading.
    worker_effective = "down" if out["worker"]["status"] == "unknown" else out["worker"]["status"]
    statuses = [out["database"]["status"], worker_effective, out["market_data"]["status"]]
    out["overall"] = ("down" if "down" in statuses
                      else "degraded" if ("degraded" in statuses or "unknown" in statuses or o_status in ("down", "degraded"))
                      else "ok")
    return out
