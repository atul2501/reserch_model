"""Point-in-time performance metrics and fitness scores per agent.

Stored as periodic snapshots (not recomputed on the fly for every dashboard
request) so equity curves and fitness history can be charted cheaply.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class PerformanceMetric(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "performance_metrics"

    agent_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    equity: Mapped[float] = mapped_column(Float, nullable=False)
    balance: Mapped[float] = mapped_column(Float, nullable=False)
    roi: Mapped[float] = mapped_column(Float, nullable=False)
    net_pnl: Mapped[float] = mapped_column(Float, nullable=False)
    gross_pnl: Mapped[float] = mapped_column(Float, nullable=False)

    win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    loss_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    expectancy: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_trade: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_winner: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_loser: Mapped[float | None] = mapped_column(Float, nullable=True)
    largest_win: Mapped[float | None] = mapped_column(Float, nullable=True)
    largest_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    consecutive_wins: Mapped[int | None] = mapped_column(Integer, nullable=True)
    consecutive_losses: Mapped[int | None] = mapped_column(Integer, nullable=True)

    max_drawdown: Mapped[float] = mapped_column(Float, nullable=False)
    sharpe_like: Mapped[float | None] = mapped_column(Float, nullable=True)
    sortino_like: Mapped[float | None] = mapped_column(Float, nullable=True)

    trade_count: Mapped[int] = mapped_column(Integer, nullable=False)
    average_holding_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    survival_seconds: Mapped[float] = mapped_column(Float, nullable=False)

    regime_performance: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    oos_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    walk_forward_score: Mapped[float | None] = mapped_column(Float, nullable=True)


class FitnessScore(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "fitness_scores"

    agent_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    fitness: Mapped[float] = mapped_column(Float, nullable=False)
    return_score: Mapped[float] = mapped_column(Float, nullable=False)
    risk_score: Mapped[float] = mapped_column(Float, nullable=False)
    consistency_score: Mapped[float] = mapped_column(Float, nullable=False)
    robustness_score: Mapped[float] = mapped_column(Float, nullable=False)
    oos_score: Mapped[float] = mapped_column(Float, nullable=False)
    drawdown_penalty: Mapped[float] = mapped_column(Float, nullable=False)
    instability_penalty: Mapped[float] = mapped_column(Float, nullable=False)

    weights_used: Mapped[dict] = mapped_column(JSONB, nullable=False)
