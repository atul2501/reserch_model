"""The auditable decision trail: for every agent evaluation, one row that
links market context -> agent signal -> risk decision -> execution outcome
(spec section 32). This is what answers "why did this agent enter this
trade?"."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import BigInteger, Float, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import Bias, RiskDecision


class Decision(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "decisions"

    agent_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    strategy_version_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("strategy_versions.id"), nullable=False
    )
    council_decision_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("council_decisions.id"), nullable=True
    )

    market_candle_open_time: Mapped[int] = mapped_column(BigInteger, nullable=False)
    market_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Snapshot of the shared market context this decision was made against.
    market_context: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Deterministic strategy evaluation output.
    agent_signal: Mapped[Bias] = mapped_column(SAEnum(Bias, name="decision_signal_enum"), nullable=False)
    agent_signal_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    agent_signal_reasoning: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    risk_decision: Mapped[RiskDecision] = mapped_column(SAEnum(RiskDecision, name="decision_risk_enum"), nullable=False)
    risk_reasoning: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    order_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True)
    trade_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("trades.id"), nullable=True)
