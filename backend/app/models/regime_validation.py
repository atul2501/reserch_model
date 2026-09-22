"""Persisted per-regime performance breakdowns and robustness
classifications (ROBUST/REGIME_SPECIALIST/FRAGILE/UNSTABLE) for a strategy
version — insert-only, so classification drift across a strategy's
lifetime (e.g. RESEARCH-stage backtest vs. later PAPER-stage reality) stays
visible instead of being overwritten.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin


class RegimeValidationReport(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "regime_validation_reports"

    strategy_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("strategy_versions.id"), nullable=False
    )

    # {regime_value: {trade_count, pnl, roi, profit_factor, win_rate,
    #                  max_drawdown_pct, expectancy}}
    per_regime: Mapped[dict] = mapped_column(JSON, nullable=False)
    classification: Mapped[str] = mapped_column(String(32), nullable=False)  # ROBUST|REGIME_SPECIALIST|FRAGILE|UNSTABLE
    classification_reasoning: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    computed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
