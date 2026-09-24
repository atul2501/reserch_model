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

from sqlalchemy import JSON, BigInteger, Boolean, Float, ForeignKey, Index, Integer, String, UniqueConstraint, Uuid, event, false, true
from sqlalchemy.orm import attributes
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

    # --- FROZEN HOLDOUT (sealed once; never recomputed as new candles arrive) ---------------------------------
    # The OOS range is fixed at seal time. `dataset_fingerprint` covers the sealed OOS slice + boundaries, so it does
    # NOT change when new candles are ingested; `oos_fingerprint` is re-verified every time the slice is loaded.
    # An epoch is renewed only by an explicit operator command (which records `renewal_reason` on the NEW epoch).
    oos_start_ms: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False, server_default="0")
    oos_end_ms: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False, server_default="0")
    oos_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, server_default=false())
    sealed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    renewal_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    supersedes_epoch_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


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
    # Reproducibility provenance beyond code/schema version: the simulation engine version and a hash of every
    # execution/risk parameter that shapes results (fees, slippage, margin, caps, fill timing, feature window...).
    engine_version: Mapped[str] = mapped_column(String(32), default="", nullable=False, server_default="")
    parameter_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False, server_default="")

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
    # Provenance (write-once with the row): which lineage consumed the slice, with which code/seed/parameters, and the
    # exact train/validation/OOS periods it was evaluated against.
    lineage_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    code_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    random_seed: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


# --- ORM-level immutability (the DB triggers in the migration are the authority; this fails fast, with a clear message,
# --- everywhere the schema is created without migrations, e.g. the test-suite) --------------------------------------
_EPOCH_SEALED = ("start_ms", "end_ms", "n_candles", "dataset_fingerprint", "train_end_ms", "validation_end_ms",
                 "oos_start_ms", "oos_end_ms", "oos_fingerprint", "symbol", "timeframe")


class ImmutableResearchRecordError(RuntimeError):
    pass


@event.listens_for(ResearchEpoch, "before_update")
def _epoch_is_sealed(mapper, connection, target):
    for col in _EPOCH_SEALED:
        if attributes.get_history(target, col, passive=attributes.PASSIVE_NO_INITIALIZE).has_changes():
            raise ImmutableResearchRecordError(f"research_epochs.{col} is sealed: the OOS holdout can only be superseded, never edited")


@event.listens_for(ResearchEpoch, "before_delete")
@event.listens_for(OosEvaluation, "before_delete")
@event.listens_for(Experiment, "before_delete")
def _never_delete(mapper, connection, target):
    raise ImmutableResearchRecordError(f"{mapper.local_table.name} rows are write-once and can never be deleted")


@event.listens_for(OosEvaluation, "before_update")
def _oos_evaluation_is_write_once(mapper, connection, target):
    raise ImmutableResearchRecordError("oos_evaluations rows are write-once: a consumed OOS result can never be rewritten")
