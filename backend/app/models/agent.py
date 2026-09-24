"""Trading agent — one independent paper/shadow/live account.

Spec sections 12-16: each agent owns its own balance, equity, positions,
trades, and PnL. Losing money in one agent must never touch another agent's
balance. Death is permanent (`status = DEAD` is a one-way transition).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, Index
from sqlalchemy import Enum as SAEnum
from sqlalchemy import Float, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin
from app.models.enums import AgentStatus


class Agent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "agents"
    __table_args__ = (
        Index("ix_agents_generation_status", 'generation', 'status'),
        Index("ix_agents_strategy_version", 'strategy_version_id'),
    )

    # Human-readable identity, e.g. GEN01-AG0001. Never reused (spec 53).
    identifier: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)

    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    strategy_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("strategy_versions.id"), nullable=False
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
    # Loss a close could not be covered by the account (the balance is floored at 0, never hidden): see
    # app/execution/accounting.py. Cash identity for a flat agent: balance == starting + realized_pnl + bad_debt.
    bad_debt: Mapped[float] = mapped_column(Float, default=0.0, nullable=False, server_default="0")

    peak_equity: Mapped[float] = mapped_column(Float, nullable=False)
    max_drawdown: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # Anchors for the daily-loss circuit breaker (risk_engine.py): reset to
    # the agent's equity whenever the candle clock rolls to a new UTC day.
    day_start_equity: Mapped[float] = mapped_column(Float, nullable=False)
    day_start_date: Mapped[date] = mapped_column(Date, nullable=False)

    trade_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    daily_trade_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_trade_time: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    cooldown_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    # DEPRECATED: the 'professional' tier classifier was removed (it was never called). The column stays because the API
    # response and dashboard still carry the field; it is always False.
    is_professional: Mapped[bool] = mapped_column(default=False, nullable=False)

    # Highest equity multiple milestone reached (2, 3, 5, 10, ...). Section 16:
    # this must never be downgraded when equity later falls.
    best_milestone_multiple: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)

    death_timestamp: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    death_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    final_equity: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)

    fitness: Mapped[float | None] = mapped_column(Float, nullable=True)
