"""AI council analyses and the consensus/judge decision built from them."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class CouncilDecision(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One consensus outcome for one candle — shared by all agents."""

    __tablename__ = "council_decisions"

    market_candle_open_time: Mapped[int] = mapped_column(BigInteger, nullable=False)
    market_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    consensus_bias: Mapped[str] = mapped_column(String(16), nullable=False)
    consensus_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    vote_tally: Mapped[dict] = mapped_column(JSONB, nullable=False)  # {"LONG": 6, "SHORT": 1, "NEUTRAL": 1}

    judge_invoked: Mapped[bool] = mapped_column(default=False, nullable=False)
    judge_response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    final_bias: Mapped[str] = mapped_column(String(16), nullable=False)
    final_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    key_risks: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    invalidators: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)


class CouncilAnalysis(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One analyst's structured response feeding into a CouncilDecision."""

    __tablename__ = "council_analyses"

    council_decision_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("council_decisions.id"), nullable=False
    )
    analyst: Mapped[str] = mapped_column(String(32), nullable=False)  # trend|momentum|structure|order_flow|...
    bias: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reasoning: Mapped[str] = mapped_column(String(4096), nullable=False)
    key_factors: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    invalidators: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    was_valid: Mapped[bool] = mapped_column(default=True, nullable=False)
    raw_response: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
