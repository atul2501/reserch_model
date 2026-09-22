"""Strategy identity, versioned DNA, generations, and immutable snapshots.

Identity rules (spec sections 16, 37, 54):
  - A `Strategy` is a stable lineage identity, e.g. STRAT-MOM-001.
  - A `StrategyVersion` is one immutable, versioned DNA payload under that
    lineage, e.g. STRAT-MOM-001:v3. Versions are never overwritten.
  - A `Generation` is the evolutionary population cohort (Gen 1, Gen 2, ...).
  - An `AgentSnapshot` freezes everything needed to reproduce an agent's
    exact behavior at a point in time. Snapshots are write-once: the service
    layer must never issue an UPDATE against this table's DNA/config columns.
"""
from __future__ import annotations

import uuid

from sqlalchemy import Enum as SAEnum
from sqlalchemy import JSON, Float, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ChampionStatus, StrategyFamily, StrategyStage


class Strategy(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A strategy lineage, e.g. STRAT-MOM-001. Immutable identity; the DNA
    itself lives on StrategyVersion rows underneath it."""

    __tablename__ = "strategies"

    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    family: Mapped[StrategyFamily] = mapped_column(SAEnum(StrategyFamily, name="strategy_family_enum"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(String(2048), default="", nullable=False)

    versions: Mapped[list["StrategyVersion"]] = relationship(back_populates="strategy")


class StrategyVersion(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "strategy_versions"
    __table_args__ = (UniqueConstraint("strategy_id", "version", name="uq_strategy_version"),)

    strategy_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("strategies.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    parent_strategy_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("strategy_versions.id"), nullable=True
    )
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    mutation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    # Full strategy DNA payload — validated against app.schemas.strategy.StrategyDNA
    # before insertion. This column is never mutated after creation.
    dna: Mapped[dict] = mapped_column(JSON, nullable=False)

    stage: Mapped[StrategyStage] = mapped_column(
        SAEnum(StrategyStage, name="strategy_stage_enum"), default=StrategyStage.RESEARCH, nullable=False
    )
    champion_status: Mapped[ChampionStatus | None] = mapped_column(
        SAEnum(ChampionStatus, name="champion_status_enum"), nullable=True
    )

    hypothesis: Mapped[str] = mapped_column(String(4096), default="", nullable=False)
    proposed_by: Mapped[str] = mapped_column(String(32), default="system", nullable=False)  # system|ollama|manual

    strategy: Mapped["Strategy"] = relationship(back_populates="versions")


class Generation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "generations"

    number: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    population_target: Mapped[int] = mapped_column(Integer, nullable=False)
    population_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    starting_balance: Mapped[float] = mapped_column(Float, nullable=False)
    total_capital_allocated: Mapped[float] = mapped_column(Float, nullable=False)

    triggered_by: Mapped[str] = mapped_column(String(64), default="initial", nullable=False)
    notes: Mapped[str] = mapped_column(String(4096), default="", nullable=False)


class AgentSnapshot(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Immutable strategy snapshot (spec section 37). Never update rows in
    this table after insert — create a new snapshot instead."""

    __tablename__ = "agent_snapshots"

    agent_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    strategy_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("strategy_versions.id"), nullable=False
    )
    generation: Mapped[int] = mapped_column(Integer, nullable=False)

    strategy_dna: Mapped[dict] = mapped_column(JSON, nullable=False)
    risk_config: Mapped[dict] = mapped_column(JSON, nullable=False)
    indicator_config: Mapped[dict] = mapped_column(JSON, nullable=False)
    model_config_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    regime_config: Mapped[dict] = mapped_column(JSON, nullable=False)

    fitness: Mapped[float | None] = mapped_column(Float, nullable=True)
    performance_metrics: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    software_version: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
