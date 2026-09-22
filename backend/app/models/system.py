"""System-level observability events (health transitions, circuit breakers,
Ollama/Hyperliquid/DB failures) — spec sections 41/47."""
from __future__ import annotations

from sqlalchemy import JSON, Boolean, Float, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import SystemEventSeverity


class SystemEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "system_events"

    component: Mapped[str] = mapped_column(String(64), nullable=False)  # ollama|hyperliquid|database|execution|risk
    severity: Mapped[SystemEventSeverity] = mapped_column(
        SAEnum(SystemEventSeverity, name="system_event_severity_enum"), nullable=False
    )
    message: Mapped[str] = mapped_column(String(2048), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class WorkerLease(Base, TimestampMixin):
    """Single durable lease guarding the decision worker per deployment."""
    __tablename__ = "worker_leases"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[float] = mapped_column(Float, nullable=False)


class WorkerCycle(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One immutable processing attempt for a confirmed market candle."""
    __tablename__ = "worker_cycles"

    cycle_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    candle_timestamp: Mapped[int] = mapped_column(nullable=False, index=True)
    cycle_started_at: Mapped[float] = mapped_column(Float, nullable=False)
    cycle_completed_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    cycle_latency_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
