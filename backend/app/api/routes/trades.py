from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.agent import Agent
from app.models.trading import Trade
from app.schemas.api import TradeSummary

router = APIRouter(prefix="/api/trades", tags=["trades"])


@router.get("", response_model=list[TradeSummary])
async def list_trades(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, le=500),
):
    stmt = (
        select(Trade, Agent.identifier)
        .join(Agent, Agent.id == Trade.agent_id)
        .order_by(Trade.closed_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return [
        TradeSummary(
            id=trade.id,
            agent_id=trade.agent_id,
            agent_identifier=identifier,
            symbol=trade.symbol,
            side=trade.side,
            quantity=trade.quantity,
            entry_price=trade.entry_price,
            exit_price=trade.exit_price,
            net_pnl=trade.net_pnl,
            gross_pnl=trade.gross_pnl,
            fees=trade.fees,
            exit_regime=trade.exit_regime,
            exit_reason=trade.exit_reason,
            opened_at=trade.opened_at,
            closed_at=trade.closed_at,
            holding_seconds=trade.holding_seconds,
        )
        for trade, identifier in result.all()
    ]
