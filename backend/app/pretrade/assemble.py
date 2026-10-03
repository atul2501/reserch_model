"""Loads everything the shadow dataset needs (READ-ONLY) and builds dataset + dashboard payload.

Shared by the /api/pretrade-shadow routes and `python -m scripts.export_pretrade_shadow`, so the dashboard and the
exported files can never disagree.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import BACKEND_DIR, Settings
from app.models.market import MarketCandle
from app.models.system import WorkerCycle
from app.models.trading import Order, Trade
from app.pretrade.dataset import CostModel, build_dataset, load_records, measured_costs
from app.pretrade.report import build_payload

COST_LOOKBACK_TRADES = 5_000


def shadow_dir(settings: Settings) -> Path:
    p = Path(settings.pretrade_shadow_dir)
    return p if p.is_absolute() else BACKEND_DIR / p


async def load_inputs(db: AsyncSession, settings: Settings, records: pd.DataFrame):
    """Candles (window + 61 min of horizon), paper entries on the candidates' bars, completed cycles, costs."""
    cand = records[records.record_type == "candidate"] if len(records) and "record_type" in records else pd.DataFrame()
    lo = int(cand.signal_bar_open_time_ms.min()) - 60_000 if len(cand) else None
    rows = []
    if lo is not None:
        q = select(MarketCandle.open_time, MarketCandle.open, MarketCandle.high, MarketCandle.low, MarketCandle.close).where(
            MarketCandle.symbol == settings.market_symbol, MarketCandle.timeframe == settings.market_timeframe,
            MarketCandle.is_final.is_(True), MarketCandle.open_time >= lo).order_by(MarketCandle.open_time)
        rows = (await db.execute(q)).all()
    candles = pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close"])

    paper = None
    if lo is not None:
        q = (select(Order.agent_id, Order.signal_candle_open_time, Order.side, Trade.entry_price, Trade.exit_price,
                    Trade.net_pnl, Trade.quantity, Trade.fees, Trade.slippage_cost, Trade.holding_seconds)
             .join(Trade, Trade.entry_order_id == Order.id, isouter=True)
             .where(Order.reduce_only.is_(False), Order.signal_candle_open_time >= lo))
        prow = (await db.execute(q)).all()
        paper = pd.DataFrame(prow, columns=["agent_id", "bar", "side", "entry_price", "exit_price", "net_pnl", "quantity",
                                            "fees", "slippage_cost", "holding_seconds"])
        if len(paper):
            paper["agent_id"] = paper.agent_id.astype(str)
            paper["side"] = paper.side.map(lambda s: getattr(s, "value", s))
            paper["notional"] = paper.entry_price * paper.quantity

    cyc = [int(t) for (t,) in (await db.execute(select(WorkerCycle.candle_timestamp).where(
        WorkerCycle.status == "COMPLETED", WorkerCycle.candle_timestamp >= (lo or 0)))).all()] if lo is not None else []

    trows = (await db.execute(select(Trade.entry_price, Trade.quantity, Trade.fees, Trade.slippage_cost)
                              .where(Trade.exit_reason != "generation_rollover")
                              .order_by(Trade.closed_at.desc()).limit(COST_LOOKBACK_TRADES))).all()
    trades = pd.DataFrame(trows, columns=["entry_price", "quantity", "fees", "slippage_cost"])
    costs = measured_costs(trades, taker_fee=settings.paper_fee_rate, slippage_bps_per_side=settings.paper_slippage_bps)
    return candles, paper, cyc, costs


async def assemble(db: AsyncSession, settings: Settings, *, horizon: int = 10, hour_group: int = 1,
                   directory: str | Path | None = None) -> tuple[pd.DataFrame, pd.DataFrame, CostModel, dict]:
    records = load_records(directory or shadow_dir(settings))
    candles, paper, cycles, costs = await load_inputs(db, settings, records)
    dataset = build_dataset(records, candles, costs, paper)
    payload = build_payload(records=records, dataset=dataset, costs=costs, completed_cycles_ms=cycles,
                            settings_view={"trading_mode": getattr(settings.trading_mode, "value", settings.trading_mode),
                                           "pretrade_mode": settings.pretrade_mode},
                            horizon=horizon, hour_group=hour_group)
    return records, dataset, costs, payload
