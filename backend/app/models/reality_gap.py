"""Persisted full-chain reality-gap reports — insert-only, one row per run,
so degradation trends across a strategy's lifetime stay visible instead of
being overwritten by the next comparison.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin


class RealityGapReport(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "reality_gap_reports"

    strategy_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("strategy_versions.id"), nullable=False
    )

    stages_present: Mapped[list] = mapped_column(JSON, nullable=False)  # ordered list of StrategyStage values reached
    transitions: Mapped[list] = mapped_column(JSON, nullable=False)  # list of compute_reality_gap()'s dicts, consecutive stages
    cumulative_gap: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # first-present -> last-present stage

    computed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
