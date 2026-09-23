"""Read/write helpers for durable system flags (kill switch, data-gap halt)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system import SystemFlag

KILL_SWITCH = "kill_switch"
DATA_GAP_HALT = "data_gap_halt"


async def set_flag(db: AsyncSession, name: str, active: bool, *, reason: str | None = None, set_by: str | None = None) -> None:
    flag = await db.get(SystemFlag, name)
    if flag is None:
        db.add(SystemFlag(name=name, active=active, reason=reason, set_by=set_by))
    else:
        flag.active = active
        flag.reason = reason
        flag.set_by = set_by
    await db.flush()


async def active_flags(db: AsyncSession) -> dict[str, str]:
    """Returns {flag_name: reason} for every currently-active flag."""
    rows = (await db.execute(select(SystemFlag).where(SystemFlag.active.is_(True)))).scalars().all()
    return {r.name: (r.reason or r.name) for r in rows}


async def trading_halt_reason(db: AsyncSession) -> str | None:
    """Single string (or None) the risk engine uses to block NEW entries."""
    flags = await active_flags(db)
    if not flags:
        return None
    return ",".join(sorted(flags))
