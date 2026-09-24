"""Persisted adversarial-suite results — insert-only, one row per run, so
robustness trends across a strategy's mutation/promotion history stay
visible instead of being overwritten.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, Float, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin


class AdversarialTestReport(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "adversarial_test_reports"

    strategy_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("strategy_versions.id"), nullable=False
    )

    worst_case_max_drawdown_pct: Mapped[float] = mapped_column(Float, nullable=False)
    worst_case_net_return_pct: Mapped[float] = mapped_column(Float, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    failure_reasons: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # Per-scenario worst-case {scenario_name: {max_drawdown_pct, net_return_pct}}
    # so the dashboard can show which stress category failed, not just an
    # aggregate pass/fail.
    scenario_breakdown: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    robustness_score: Mapped[float] = mapped_column(Float, nullable=False)

    computed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    # Provenance - what is needed to reproduce this exact run (see AdversarialConfig).
    experiment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    random_seed: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    scenario_config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    dataset_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    code_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
