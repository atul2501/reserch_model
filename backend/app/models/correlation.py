"""Persisted strategy-correlation data — insert-only per generation, so
population convergence can be analyzed across generations (never
overwritten). `agent_correlations` holds only the top-N most-correlated
pairs per generation, not the full n^2 matrix — at 500 agents that's
~125k pairs, and only the tail matters for diversity-pressure decisions
and dashboard display.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Uuid, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin


class AgentCorrelation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "agent_correlations"
    __table_args__ = (
        Index("ix_agent_corr_a", 'agent_id_a'),
        Index("ix_agent_corr_b", 'agent_id_b'),
    )

    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_id_a: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    agent_id_b: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    strategy_family_a: Mapped[str] = mapped_column(String(32), nullable=False)
    strategy_family_b: Mapped[str] = mapped_column(String(32), nullable=False)

    dna_similarity: Mapped[float] = mapped_column(Float, nullable=False)
    feature_similarity: Mapped[float] = mapped_column(Float, nullable=False)
    entry_condition_similarity: Mapped[float] = mapped_column(Float, nullable=False)
    exit_condition_similarity: Mapped[float] = mapped_column(Float, nullable=False)
    trade_direction_correlation: Mapped[float | None] = mapped_column(Float, nullable=True)
    return_correlation: Mapped[float | None] = mapped_column(Float, nullable=True)
    position_overlap: Mapped[float | None] = mapped_column(Float, nullable=True)
    trade_timing_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    composite_correlation: Mapped[float] = mapped_column(Float, nullable=False)

    computed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)


class StrategyFamilyCorrelation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "strategy_family_correlations"

    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    family_a: Mapped[str] = mapped_column(String(32), nullable=False)
    family_b: Mapped[str] = mapped_column(String(32), nullable=False)
    mean_correlation: Mapped[float] = mapped_column(Float, nullable=False)
    member_pair_count: Mapped[int] = mapped_column(Integer, nullable=False)

    computed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)


class CorrelationConvergenceSnapshot(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One row per generation — the correlation-history-across-generations
    store StrategyCorrelationEngine exists to provide."""

    __tablename__ = "correlation_convergence_snapshots"

    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    population_diversity_score: Mapped[float] = mapped_column(Float, nullable=False)
    mean_pairwise_correlation: Mapped[float] = mapped_column(Float, nullable=False)
    pct_agents_above_max_correlation: Mapped[float] = mapped_column(Float, nullable=False)
    family_distribution: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    diversity_pressure_applied: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    actions_taken: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    computed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
