"""System-level observability events (health transitions, circuit breakers,
Ollama/Hyperliquid/DB failures) — spec sections 41/47."""
from __future__ import annotations

from sqlalchemy import JSON
from sqlalchemy import Enum as SAEnum
from sqlalchemy import String
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
