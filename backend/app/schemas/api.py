"""Pydantic response models for the public API (spec section 33). Kept
separate from ORM models so the API contract can evolve independently of
storage schema, and so secrets/internal fields never leak by accident."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.enums import AgentStatus, MarketRegime, Side


class AgentSummary(BaseModel):
    id: uuid.UUID
    identifier: str
    generation: int
    status: AgentStatus
    strategy_version_id: uuid.UUID
    balance: float
    equity: float
    starting_balance: float
    roi: float
    realized_pnl: float
    max_drawdown: float
    trade_count: int
    is_professional: bool
    best_milestone_multiple: float
    fitness: float | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AgentDetail(AgentSummary):
    fees_paid: float
    funding_paid: float
    peak_equity: float
    death_timestamp: datetime | None
    death_reason: str | None
    final_equity: float | None
    final_pnl: float | None


class LeaderboardEntry(BaseModel):
    rank: int
    agent: AgentSummary
    strategy_family: str | None


class MarketSnapshot(BaseModel):
    symbol: str
    close_price: float                   # close of the last CONFIRMED candle
    regime: MarketRegime
    regime_confidence: float
    candle_open_time: int                # open time of the last CONFIRMED candle
    volatility_percentile: float
    volume_ratio: float
    timeframe: str = "1m"
    confirmed_candle_close_time: int | None = None
    data_freshness_seconds: float | None = None
    market_data_stale: bool | None = None
    live_price: float | None = None      # current OPEN candle close — display only, never traded on
    live_candle_open_time: int | None = None


class PopulationSummary(BaseModel):
    generation: int
    target_size: int
    active_count: int
    dead_count: int
    professional_count: int
    total_equity: float
    total_realized_pnl: float
    total_capital_allocated: float
    retired_count: int = 0
    total_count: int = 0
    generations_total: int = 0
    mean_equity: float | None = None
    best_equity: float | None = None
    worst_equity: float | None = None
    total_fees_paid: float = 0.0
    total_funding_paid: float = 0.0


class CandlePoint(BaseModel):
    open_time: int
    close: float


class PositionSummary(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    agent_identifier: str
    symbol: str
    side: Side
    quantity: float
    entry_price: float
    leverage: float
    unrealized_pnl: float
    opened_at: datetime
    strategy_family: str | None
    # The trading engine evaluates stop-loss/take-profit rules live each
    # cycle rather than storing a fixed trigger price on the position, so
    # these describe the strategy's *rule* (from its DNA), not a price.
    take_profit_method: str | None
    take_profit_value: float | None
    stop_loss_method: str | None
    stop_loss_value: float | None


class TradeSummary(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    agent_identifier: str
    symbol: str
    side: Side
    quantity: float
    entry_price: float
    exit_price: float
    net_pnl: float
    gross_pnl: float
    fees: float
    exit_regime: str | None
    exit_reason: str
    opened_at: datetime
    closed_at: datetime
    holding_seconds: int


class RegimePerformance(BaseModel):
    regime: str
    trade_count: int
    win_count: int
    win_rate: float
    total_pnl: float
    avg_pnl: float


class SidePerformance(BaseModel):
    side: Side
    trade_count: int
    win_count: int
    win_rate: float
    total_pnl: float
    avg_pnl: float


class SystemHealth(BaseModel):
    database_ok: bool
    hyperliquid_configured: bool
    ollama_configured: bool
    trading_mode: str
    market_data_stale: bool | None
    last_candle_age_seconds: float | None
