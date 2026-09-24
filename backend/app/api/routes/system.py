from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.enums import SystemEventSeverity
from app.models.system import SystemEvent
from app.core.database import get_db
from app.core.security import Principal, Role, require_role
from app.core.system_flags import KILL_SWITCH, active_flags, set_flag
from app.core.runtime_status import compute_system_status
from app.schemas.api import SystemHealth

router = APIRouter(prefix="/api/system", tags=["system"])
logger = get_logger(__name__)


@router.get("/health", response_model=SystemHealth)
async def health(db: AsyncSession = Depends(get_db)):
    """Backward-compatible summary (the rich picture is /api/system/status). No
    outbound HTTP client is created per request any more."""
    settings = get_settings()
    status = await compute_system_status(db)
    database_ok = status["database"]["status"] == "ok"
    md = status.get("market_data", {})
    payload = SystemHealth(
        database_ok=database_ok,
        hyperliquid_configured=bool(settings.hyperliquid_api_url),
        ollama_configured=bool(settings.ollama_base_url and settings.ollama_model),
        trading_mode=settings.trading_mode.value,
        market_data_stale=None if not database_ok or md.get("status") == "unknown" else md.get("status") == "down",
        last_candle_age_seconds=md.get("freshness_seconds"),
    )
    if not database_ok:
        # A dead database must be visible to load balancers/monitors, not a 200.
        return JSONResponse(status_code=503, content=payload.model_dump(mode="json"))
    return payload


class KillSwitchRequest(BaseModel):
    active: bool
    reason: str = Field(default="", max_length=500)


@router.get("/flags")
async def get_flags(db: AsyncSession = Depends(get_db)):
    return {"active_flags": await active_flags(db)}


@router.post("/kill-switch")
async def set_kill_switch(
    request: Request,
    body: KillSwitchRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role(Role.OPERATOR)),
):
    """Emergency stop. Blocks every NEW entry across the population (exits and
    risk management keep running). Requires operator or admin — a viewer key
    never gets control-plane access."""
    was_active = KILL_SWITCH in await active_flags(db)
    await set_flag(db, KILL_SWITCH, body.active, reason=body.reason or None, set_by=principal.name)
    # AUDIT: the flag row only holds the latest value, so every change is also written as an append-only event
    # (who, when, from -> to, why, from where) and logged.
    client = request.client.host if request.client else "unknown"
    db.add(SystemEvent(
        component="api", severity=SystemEventSeverity.WARNING if body.active else SystemEventSeverity.INFO,
        message=f"kill_switch {'ENGAGED' if body.active else 'released'} by {principal.name}",
        detail={"action": "kill_switch", "was_active": was_active, "now_active": body.active, "principal": principal.name,
                "role": principal.role.name, "reason": body.reason or None, "client": client},
    ))
    await db.commit()
    logger.warning("api.kill_switch_changed", principal=principal.name, was_active=was_active, now_active=body.active,
                   reason=body.reason or None, client=client)
    return {"kill_switch": body.active, "set_by": principal.name}
