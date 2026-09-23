"""Health, runtime status, realtime stream (SSE) and metrics (spec phases 36-37)."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import metrics
from app.core.database import AsyncSessionLocal, get_db
from app.core.runtime_status import WORKER, compute_system_status, read_status
from app.core.security import Principal, Role, require_role
from app.models.agent import Agent
from app.models.council import CouncilDecision
from app.models.enums import AgentStatus
from app.models.trading import Order, Trade

router = APIRouter(tags=["status"])


@router.get("/api/system/status")
async def system_status(db: AsyncSession = Depends(get_db)):
    status = await compute_system_status(db)
    return JSONResponse(status_code=503 if status["overall"] == "down" and status["database"]["status"] == "down" else 200, content=status)


@router.get("/api/system/ollama")
async def ollama_health(db: AsyncSession = Depends(get_db), _: Principal = Depends(require_role(Role.OPERATOR))):
    """Credential health by INDEX only (never the key itself) + last council outcome."""
    payload = await read_status(db, WORKER) or {}
    last = (await db.execute(select(CouncilDecision).order_by(CouncilDecision.created_at.desc()).limit(1))).scalar_one_or_none()
    return {
        "keys": payload.get("ollama_keys"),
        "last_council": None if last is None else {
            "status": last.council_status, "candle_open_time": last.market_candle_open_time,
            "successful_analysts": last.successful_analysts, "expected_analysts": last.expected_analysts,
            "failure_reasons": last.failure_reasons, "latency_seconds": last.total_council_latency_seconds,
        },
    }


async def _db_gauges(db: AsyncSession) -> list[str]:
    lines: list[str] = []
    for status, n in (await db.execute(select(Agent.status, func.count()).group_by(Agent.status))).all():
        lines.append(f'agents{{status="{status.value}"}} {n}')
    equity = (await db.execute(select(func.coalesce(func.sum(Agent.equity), 0.0)).where(Agent.status == AgentStatus.ACTIVE))).scalar_one()
    lines.append(f"population_equity {float(equity)}")
    for status, n in (await db.execute(select(Order.status, func.count()).group_by(Order.status))).all():
        lines.append(f'orders_by_status{{status="{status.value}"}} {n}')
    lines.append(f"trades_closed {(await db.execute(select(func.count()).select_from(Trade))).scalar_one()}")
    lines.append(f'council_decisions{{status="INCOMPLETE"}} {(await db.execute(select(func.count()).select_from(CouncilDecision).where(CouncilDecision.council_status == "INCOMPLETE"))).scalar_one()}')
    lines.append(f'council_decisions{{status="COMPLETE"}} {(await db.execute(select(func.count()).select_from(CouncilDecision).where(CouncilDecision.council_status == "COMPLETE"))).scalar_one()}')
    st = await compute_system_status(db)
    lc = (st.get("worker") or {}).get("last_cycle") or {}
    if lc.get("latency_seconds") is not None:
        lines.append(f"last_cycle_latency_seconds {lc['latency_seconds']}")
    if st.get("market_data", {}).get("freshness_seconds") is not None:
        lines.append(f"market_data_freshness_seconds {st['market_data']['freshness_seconds']}")
    for comp in ("database", "worker", "market_data", "hyperliquid", "ollama"):
        lines.append(f'component_up{{component="{comp}"}} {1 if st.get(comp, {}).get("status") == "ok" else 0}')
    return lines


@router.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics(db: AsyncSession = Depends(get_db), _: Principal = Depends(require_role(Role.OPERATOR))):
    """API-process counters + worker-published counters + DB-derived gauges (Prometheus text)."""
    payload = await read_status(db, WORKER) or {}
    parts = ["# --- api process ---", metrics.render_prometheus().rstrip(), "# --- worker process ---",
             (payload.get("metrics_text") or "").rstrip(), "# --- database-derived ---", *await _db_gauges(db)]
    return "\n".join(parts) + "\n"


@router.get("/api/stream")
async def stream(request: Request, _: Principal = Depends(require_role(Role.VIEWER)), interval: float = 2.0, max_events: int | None = None):
    """Server-Sent Events: a `status` event every `interval` seconds (worker
    heartbeat, last confirmed candle, last cycle, cycle latency, data freshness,
    Ollama health), and a `cycle` event whenever a new candle has been processed.
    Fetch-based clients send the API key as a header (EventSource cannot)."""
    interval = max(0.5, min(interval, 30.0))

    async def gen():
        last_cycle = None
        sent = 0
        while not await request.is_disconnected():
            async with AsyncSessionLocal() as db:
                status = await compute_system_status(db)
            cycle = (status.get("worker") or {}).get("last_cycle") or {}
            if cycle.get("cycle_id") and cycle["cycle_id"] != last_cycle:
                last_cycle = cycle["cycle_id"]
                yield f"event: cycle\nid: {last_cycle}\ndata: {json.dumps(cycle)}\n\n"
            yield f"event: status\ndata: {json.dumps(status, default=str)}\n\n"
            sent += 1
            if max_events is not None and sent >= max_events:
                return
            await asyncio.sleep(interval)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
