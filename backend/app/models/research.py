"""Experiment registry, research epochs (dataset registry) and the OOS lockbox
(spec phase 23).

  ResearchEpoch  a frozen, fingerprinted candle window split chronologically
                 into TRAIN / VALIDATION / FINAL-OOS. Evolution only ever reads
                 train/validation; the OOS slice is opened exclusively through
                 `app.research.lockbox`, at most once per (strategy version,
                 dataset fingerprint).
  Experiment     one reproducible research run: what data (fingerprint,
                 periods), which strategy/params, which code + schema version,
                 which random seed.
  OosEvaluation  the write-once record that a version consumed the OOS slice of
                 a dataset (unique => "no repeated tuning against the final test").
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, Float, ForeignKey, Index, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin


class ResearchEpoch(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "research_epochs"
    __table_args__ = (UniqueConstraint("dataset_fingerprint", name="uq_epoch_fingerprint"),)

    epoch_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    start_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    n_candles: Mapped[int] = mapped_column(Integer, nullable=False)
    dataset_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    # Chronological boundaries: train [start, train_end_ms], validation
    # (train_end_ms, validation_end_ms], final OOS (validation_end_ms, end].
    train_end_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    validation_end_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    oos_locked: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Experiment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "experiments"
    __table_args__ = (
        Index("ix_experiments_kind_created", "kind", "created_at"),
        Index("ix_experiments_version", "strategy_version_id"),
    )

    experiment_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)  # evolution | evaluation | oos
    status: Mapped[str] = mapped_column(String(16), default="RUNNING", nullable=False)  # RUNNING|COMPLETED|SKIPPED|FAILED

    epoch_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dataset_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    train_period: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    validation_period: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    oos_period: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    strategy_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("strategy_versions.id"), nullable=True
    )
    generation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parameters: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    code_version: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    random_seed: Mapped[int] = mapped_column(BigInteger, nullable=False)

    result: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class OosEvaluation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "oos_evaluations"
    __table_args__ = (
        UniqueConstraint("strategy_version_id", "dataset_fingerprint", name="uq_oos_once_per_version_dataset"),
    )

    strategy_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("strategy_versions.id"), nullable=False
    )
    dataset_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    experiment_id: Mapped[str] = mapped_column(String(64), nullable=False)
    oos_score: Mapped[float] = mapped_column(Float, nullable=False)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
