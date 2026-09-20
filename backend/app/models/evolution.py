"""Evolution and population lifecycle event logs."""
from __future__ import annotations

import uuid

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import EvolutionEventType, PopulationEventType, PopulationStatus


class EvolutionEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "evolution_events"

    event_type: Mapped[EvolutionEventType] = mapped_column(
        SAEnum(EvolutionEventType, name="evolution_event_type_enum"), nullable=False
    )
    parent_strategy_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("strategy_versions.id"), nullable=True
    )
    parent_strategy_version_id_2: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("strategy_versions.id"), nullable=True
    )  # second parent, for crossover
    child_strategy_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("strategy_versions.id"), nullable=True
    )

    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    hypothesis: Mapped[str] = mapped_column(String(4096), default="", nullable=False)
    ollama_analysis: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    validation_result: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    accepted: Mapped[bool | None] = mapped_column(nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)


class PopulationEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "population_events"

    event_type: Mapped[PopulationEventType] = mapped_column(
        SAEnum(PopulationEventType, name="population_event_type_enum"), nullable=False
    )
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    population_status: Mapped[PopulationStatus] = mapped_column(
        SAEnum(PopulationStatus, name="population_status_enum"), nullable=False
    )
    detail: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    report: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)  # extinction/generation research report
