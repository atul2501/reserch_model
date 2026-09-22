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
    close_price: float
    regime: MarketRegime
    regime_confidence: float
    candle_open_time: int
    volatility_percentile: float
    volume_ratio: float


class PopulationSummary(BaseModel):
    generation: int
    target_size: int
    active_count: int
    dead_count: int
    professional_count: int
    total_equity: float
    total_realized_pnl: float
    total_capital_allocated: float


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


class SystemHealth(BaseModel):
    database_ok: bool
    hyperliquid_configured: bool
    ollama_configured: bool
    trading_mode: str
    market_data_stale: bool | None
    last_candle_age_seconds: float | None
