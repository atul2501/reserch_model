"""Which agents can be TESTED at their capital (Option D of the min-notional sizing analysis).

A flat agent whose configured size cannot reach the exchange minimum (`paper_min_order_notional`) has every entry
refused at decision time (Decision reason `below_min_order_notional`, see `decision_loop`). Such an agent is not a
failed strategy - it never got to trade - and ranking it against agents that did trade is meaningless: with a
negative-edge population the fitness function scores inaction above losing trades. So it is REPORTED as untestable
and EXCLUDED from survivor ranking. Its DNA, sizing, risk limits and status are untouched; the state is derived from
durable rows (Decisions + `Agent.trade_count`), never stored, so it clears by itself once the agent starts to trade.
"""
from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Iterable

from sqlalchemy import String, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.agent import Agent
from app.models.decision import Decision

MIN_NOTIONAL_REASON = "below_min_order_notional"


def is_untestable(*, blocked: int, executed: int, min_blocked: int, blocked_share: float) -> bool:
    """`blocked` entry attempts refused by the minimum vs `executed` entries actually opened."""
    if blocked < max(1, min_blocked):
        return False   # too little evidence either way (an agent that never signalled is NOT untestable)
    return blocked / (blocked + executed) >= blocked_share


async def blocked_entry_counts(db: AsyncSession, agent_ids: Iterable[uuid.UUID]) -> Counter:
    """Entry attempts refused by the exchange minimum, per agent (one grouped query)."""
    ids = list(agent_ids)
    if not ids:
        return Counter()
    rows = (await db.execute(
        select(Decision.agent_id, func.count())
        .where(Decision.agent_id.in_(ids), cast(Decision.risk_reasoning, String).like(f"%{MIN_NOTIONAL_REASON}%"))
        .group_by(Decision.agent_id)
    )).all()
    return Counter({agent_id: n for agent_id, n in rows})


async def untestable_agent_ids(db: AsyncSession, agents: Iterable[Agent]) -> set[uuid.UUID]:
    agents = list(agents)
    settings = get_settings()
    blocked = await blocked_entry_counts(db, (a.id for a in agents))
    return {
        a.id for a in agents
        if is_untestable(blocked=blocked[a.id], executed=a.trade_count,
                         min_blocked=settings.untestable_min_blocked_entries, blocked_share=settings.untestable_blocked_share)
    }
