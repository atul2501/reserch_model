from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.market.regime_lookup import load_regime_lookup, regime_at
from app.models.agent import Agent
from app.models.enums import Side
from app.models.strategy import Strategy, StrategyVersion
from app.models.trading import Trade
from app.schemas.api import RegimePerformance, SidePerformance, StrategyPerformance, TradeSummary

router = APIRouter(prefix="/api/trades", tags=["trades"])


@router.get("", response_model=list[TradeSummary])
async def list_trades(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, le=500),
):
    stmt = (
        select(Trade, Agent.identifier, Strategy.family)
        .join(Agent, Agent.id == Trade.agent_id)
        .outerjoin(StrategyVersion, StrategyVersion.id == Agent.strategy_version_id)
        .outerjoin(Strategy, Strategy.id == StrategyVersion.strategy_id)
        .order_by(Trade.closed_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return [
        TradeSummary(
            id=trade.id,
            agent_id=trade.agent_id,
            agent_identifier=identifier,
            strategy_family=family.value if family is not None else None,
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
        for trade, identifier, family in result.all()
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

    open_times, regimes = await load_regime_lookup(db)

    buckets: dict[str, list[float]] = {}
    for net_pnl, closed_at in trades:
        regime = regime_at(int(closed_at.timestamp() * 1000), open_times, regimes)
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


@router.get("/by-strategy", response_model=list[StrategyPerformance])
async def get_strategy_performance(db: AsyncSession = Depends(get_db)):
    """Breaks down closed-trade performance by strategy family.

    A trade's strategy is its agent's strategy version's family (same join
    as the leaderboard). Aggregated in SQL since the trades table grows
    without bound. Agents with no strategy version land in a null bucket.
    """
    stmt = (
        select(
            Strategy.family,
            func.count(func.distinct(Trade.agent_id)),
            func.count(Trade.id),
            func.sum(case((Trade.net_pnl > 0, 1), else_=0)),
            func.sum(Trade.net_pnl),
            func.sum(Trade.fees),
        )
        .join(Agent, Agent.id == Trade.agent_id)
        .outerjoin(StrategyVersion, StrategyVersion.id == Agent.strategy_version_id)
        .outerjoin(Strategy, Strategy.id == StrategyVersion.strategy_id)
        .group_by(Strategy.family)
    )
    rows = (await db.execute(stmt)).all()
    grand_total = sum(row[2] for row in rows)
    grand_wins = sum(int(row[3] or 0) for row in rows)
    results = []
    for family, agents, count, wins, total_pnl, total_fees in rows:
        wins = int(wins or 0)
        total_pnl = float(total_pnl or 0.0)
        results.append(
            StrategyPerformance(
                strategy_family=family.value if family is not None else None,
                agent_count=agents,
                trade_count=count,
                win_count=wins,
                win_rate=wins / count,
                total_pnl=total_pnl,
                avg_pnl=total_pnl / count,
                total_fees=float(total_fees or 0.0),
                trade_share=count / grand_total,
                win_share=wins / grand_wins if grand_wins else 0.0,
            )
        )
    results.sort(key=lambda r: r.total_pnl, reverse=True)
    return results
