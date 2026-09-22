"""Deterministic Candidate -> Validation -> Challenger -> Observation ->
Champion Comparison -> Promotion Decision pipeline state, per strategy
version — insert-only per stage transition, so the full evaluation history
is preserved (never overwritten) rather than just the current state.

Kept distinct from `StrategyVersion.stage` (StrategyStage: RESEARCH/
BACKTEST/.../APPROVED_LIVE — the backtest-to-live pipeline position) and
from `StrategyVersion.champion_status` (the coarse CHAMPION/CHALLENGER/
RETIRED/REJECTED state promotion_service.py flips) — `pipeline_stage` here
is the finer-grained champion/challenger EVALUATION phase the two other
axes don't represent.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin

PIPELINE_STAGES = (
    "candidate",
    "validation",
    "challenger",
    "observation",
    "champion_comparison",
    "promoted",
    "rejected",
)


class ChallengerEvaluation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "challenger_evaluations"

    strategy_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("strategy_versions.id"), nullable=False
    )
    pipeline_stage: Mapped[str] = mapped_column(String(32), nullable=False)
    entered_stage_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    min_observation_days_required: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Correlation/reality-gap/adversarial/regime-validation results captured
    # at the moment of this transition — an audit trail of exactly what was
    # known when the decision was made.
    metrics_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    blocking_reasons: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    computed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
