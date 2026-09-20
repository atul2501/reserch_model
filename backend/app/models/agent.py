"""Trading agent — one independent paper/shadow/live account.

Spec sections 12-16: each agent owns its own balance, equity, positions,
trades, and PnL. Losing money in one agent must never touch another agent's
balance. Death is permanent (`status = DEAD` is a one-way transition).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import AgentStatus


class Agent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "agents"

    # Human-readable identity, e.g. GEN01-AG0001. Never reused (spec 53).
    identifier: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)

    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    strategy_version_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("strategy_versions.id"), nullable=False
    )

    status: Mapped[AgentStatus] = mapped_column(
        SAEnum(AgentStatus, name="agent_status_enum"), default=AgentStatus.ACTIVE, nullable=False
    )

    starting_balance: Mapped[float] = mapped_column(Float, nullable=False)
    balance: Mapped[float] = mapped_column(Float, nullable=False)  # cash, excludes unrealized PnL
    equity: Mapped[float] = mapped_column(Float, nullable=False)  # balance + unrealized PnL

    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    fees_paid: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    funding_paid: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    peak_equity: Mapped[float] = mapped_column(Float, nullable=False)
    max_drawdown: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    trade_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_professional: Mapped[bool] = mapped_column(default=False, nullable=False)

    # Highest equity multiple milestone reached (2, 3, 5, 10, ...). Section 16:
    # this must never be downgraded when equity later falls.
    best_milestone_multiple: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)

    death_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    death_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    final_equity: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)

    fitness: Mapped[float | None] = mapped_column(Float, nullable=True)
