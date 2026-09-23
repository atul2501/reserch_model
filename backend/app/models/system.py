"""System-level observability events (health transitions, circuit breakers,
Ollama/Hyperliquid/DB failures) — spec sections 41/47."""
from __future__ import annotations

from sqlalchemy import JSON, BigInteger, Boolean, Float, String, Text
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
    # Fencing token: incremented on every ownership change so a paused,
    # superseded worker can be detected.
    epoch: Mapped[int] = mapped_column(default=0, nullable=False)
    heartbeat_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class WorkerCycle(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One immutable processing attempt for a confirmed market candle."""
    __tablename__ = "worker_cycles"

    cycle_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    candle_timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    cycle_started_at: Mapped[float] = mapped_column(Float, nullable=False)
    cycle_completed_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    cycle_latency_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # STARTED | COMPLETED | FAILED | SKIPPED_CATCHUP. A STARTED/FAILED cycle is
    # re-run (idempotently, via the per-agent decision unique constraint) on
    # restart — a crash mid-cycle never loses the candle.
    status: Mapped[str] = mapped_column(String(24), default="STARTED", nullable=False)
    attempts: Mapped[int] = mapped_column(default=1, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    council_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    agents_processed: Mapped[int | None] = mapped_column(nullable=True)
    trading_halt_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)


class SystemFlag(Base, TimestampMixin):
    """Durable operator/system switches read by the worker every cycle.

    `kill_switch`      — operator emergency stop: no new entries, exits continue.
    `data_gap_halt`    — set by the market-data layer when a candle gap could not
                         be recovered; cleared automatically once continuity is
                         restored. Never trade through an unknown data gap.
    """
    __tablename__ = "system_flags"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    set_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class SystemStatus(Base, TimestampMixin):
    """Latest runtime snapshot published by a background process (the trading
    worker). Lets the API process report worker/Ollama/WebSocket/metrics state
    that lives in another process's memory."""
    __tablename__ = "system_status"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
