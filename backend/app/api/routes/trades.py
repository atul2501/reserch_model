from __future__ import annotations

import bisect

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.agent import Agent
from app.models.enums import Side
from app.models.market import MarketRegimeRecord
from app.models.trading import Trade
from app.schemas.api import RegimePerformance, SidePerformance, TradeSummary

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


@router.get("/by-regime", response_model=list[RegimePerformance])
async def get_regime_performance(db: AsyncSession = Depends(get_db)):
    """Breaks down closed-trade performance by the market regime that was
    active when each trade closed.

    Trade.exit_regime is never actually set by the trading engine (it
    evaluates fills live rather than stamping a regime onto the row), so
    this reconstructs it: for each trade's close time, find the most recent
    MarketRegimeRecord at or before that moment — the same regime the
    shared market pipeline had classified at the time — and aggregate
    win rate / PnL per regime from that.
    """
    trades = (await db.execute(select(Trade.net_pnl, Trade.closed_at))).all()
    if not trades:
        return []

    regime_rows = (
        await db.execute(select(MarketRegimeRecord.candle_open_time, MarketRegimeRecord.regime).order_by(MarketRegimeRecord.candle_open_time))
    ).all()
    open_times = [row[0] for row in regime_rows]
    regimes = [row[1].value for row in regime_rows]

    buckets: dict[str, list[float]] = {}
    for net_pnl, closed_at in trades:
        if open_times:
            idx = bisect.bisect_right(open_times, int(closed_at.timestamp() * 1000)) - 1
            regime = regimes[idx] if idx >= 0 else "UNKNOWN"
        else:
            regime = "UNKNOWN"
        buckets.setdefault(regime, []).append(net_pnl)

    results = []
    for regime, pnls in buckets.items():
        wins = sum(1 for p in pnls if p > 0)
        results.append(
            RegimePerformance(
                regime=regime,
                trade_count=len(pnls),
                win_count=wins,
                win_rate=wins / len(pnls),
                total_pnl=sum(pnls),
                avg_pnl=sum(pnls) / len(pnls),
            )
        )
    results.sort(key=lambda r: r.trade_count, reverse=True)
    return results


@router.get("/by-side", response_model=list[SidePerformance])
async def get_side_performance(db: AsyncSession = Depends(get_db)):
    """Breaks down closed-trade performance by LONG vs SHORT.

    Unlike regime (reconstructed from timestamps), side is a direct column
    on Trade, so this is a straight groupby. Useful as a second fee-vs-edge
    tell alongside /by-regime: a side with a healthy win rate but ~$0
    avg_pnl means wins are barely covering entry+exit fees on that side,
    same signature as the LOW_VOLATILITY regime case.
    """
    trades = (await db.execute(select(Trade.net_pnl, Trade.side))).all()
    if not trades:
        return []

    buckets: dict[Side, list[float]] = {}
    for net_pnl, side in trades:
        buckets.setdefault(side, []).append(net_pnl)

    results = []
    for side, pnls in buckets.items():
        wins = sum(1 for p in pnls if p > 0)
        results.append(
            SidePerformance(
                side=side,
                trade_count=len(pnls),
                win_count=wins,
                win_rate=wins / len(pnls),
                total_pnl=sum(pnls),
                avg_pnl=sum(pnls) / len(pnls),
            )
        )
    results.sort(key=lambda r: r.trade_count, reverse=True)
    return results
