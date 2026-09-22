from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.agent import Agent
from app.models.strategy import Strategy, StrategyVersion
from app.models.trading import Position
from app.schemas.api import PositionSummary

router = APIRouter(prefix="/api/positions", tags=["positions"])


@router.get("", response_model=list[PositionSummary])
async def list_open_positions(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=100, le=500),
):
    stmt = (
        select(Position, Agent.identifier, StrategyVersion.dna, Strategy.family)
        .join(Agent, Agent.id == Position.agent_id)
        .outerjoin(StrategyVersion, StrategyVersion.id == Agent.strategy_version_id)
        .outerjoin(Strategy, Strategy.id == StrategyVersion.strategy_id)
        .where(Position.is_open.is_(True))
        .order_by(Position.opened_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    summaries = []
    for position, identifier, dna, family in result.all():
        take_profit = (dna or {}).get("take_profit") or {}
        stop_loss = (dna or {}).get("stop_loss") or {}
        summaries.append(
            PositionSummary(
                id=position.id,
                agent_id=position.agent_id,
                agent_identifier=identifier,
                symbol=position.symbol,
                side=position.side,
                quantity=position.quantity,
                entry_price=position.entry_price,
                leverage=position.leverage,
                unrealized_pnl=position.unrealized_pnl,
                opened_at=position.opened_at,
                strategy_family=family.value if family is not None else None,
                take_profit_method=take_profit.get("method") if take_profit.get("enabled") else None,
                take_profit_value=take_profit.get("value") if take_profit.get("enabled") else None,
                stop_loss_method=stop_loss.get("method") if stop_loss.get("enabled") else None,
                stop_loss_value=stop_loss.get("value") if stop_loss.get("enabled") else None,
            )
        )
    return summaries
