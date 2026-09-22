"""Persisted performance snapshots per pipeline stage (spec sections 22-24,
34), so a strategy version's Backtest -> Paper -> Shadow -> Live performance
can be compared to measure the "reality gap" between simulated and real
execution instead of being discarded after each run.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Float, ForeignKey, Integer, Uuid
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin
from app.models.enums import StrategyStage


class StageMetrics(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One performance snapshot for a StrategyVersion at a given pipeline
    stage. Multiple rows per (strategy_version_id, stage) are allowed —
    always compare against the most recent by `computed_at` unless a caller
    explicitly wants history."""

    __tablename__ = "stage_metrics"

    strategy_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("strategy_versions.id"), nullable=False
    )
    stage: Mapped[StrategyStage] = mapped_column(SAEnum(StrategyStage, name="strategy_stage_enum"), nullable=False)

    net_return_pct: Mapped[float] = mapped_column(Float, nullable=False)
    max_drawdown_pct: Mapped[float] = mapped_column(Float, nullable=False)
    win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    trade_count: Mapped[int] = mapped_column(Integer, nullable=False)

    # Sourced from walk-forward/out-of-sample runs; feed champion/challenger
    # promotion criteria (evolution/champion.py) once persisted here.
    oos_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    walk_forward_consistency: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Reality-gap fields: PnL alone hides *why* a stage underperformed the
    # one before it — cost drag (fees/funding/slippage) vs execution
    # quality (latency/missed fills) are different failure modes with
    # different fixes. Nullable because backtest/walk-forward stages don't
    # populate all of them (no real fill latency exists in a backtest).
    total_fees: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_funding: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_slippage_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_trade_net_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    missed_trade_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    missed_trade_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_signal_to_fill_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    computed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
