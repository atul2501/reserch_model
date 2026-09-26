"""Derived analytical tables (the analytics foundation).

These tables store ONLY derived values, recomputable from the raw trading
tables (trades / positions / orders / decisions / market_candles /
market_regimes / fitness_scores). The analytics layer NEVER modifies a raw
table; `scripts/refresh_analytics.py` is the only writer and writes only here.

  TradeAnalytics               1:1 with a closed Trade: entry/exit quality,
                               MFE/MAE replayed over confirmed candles, the
                               trade-quality classification, and the outcome
                               of the replay-vs-persisted-extremes cross-check.
  StrategyRegimeMatrix         one aggregate cell per (window, granularity,
                               dim, regime) with Wilson/bootstrap intervals and
                               an evidence state.
  FitnessForwardPerformance    append-only EVIDENCE (insert-only, ORM listener
                               + DB trigger): the fitness an agent had at T vs
                               its strictly-later realized performance. Rows are
                               immutable because recomputing them with later
                               knowledge would defeat the study's purpose.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, Float, ForeignKey, Index, Integer, String, Uuid, event
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin


class TradeAnalytics(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "trade_analytics"
    __table_args__ = (
        Index("uq_trade_analytics_trade", "trade_id", unique=True),
        Index("ix_trade_analytics_agent", "agent_id"),
        Index("ix_trade_analytics_family_regime", "family", "regime"),
        Index("ix_trade_analytics_regime", "regime"),
        Index("ix_trade_analytics_version", "strategy_version_id"),
        Index("ix_trade_analytics_class", "trade_quality_class"),
    )

    trade_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("trades.id"), nullable=False)
    # Denormalised grouping keys (the whole point of this table): the point-in-time
    # strategy identity comes from the entry DECISION, never from the mutable
    # Agent.strategy_version_id.
    agent_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    family: Mapped[str | None] = mapped_column(String(16), nullable=True)
    strategy_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    regime: Mapped[str | None] = mapped_column(String(32), nullable=True)
    side: Mapped[str] = mapped_column(String(5), nullable=False)

    # --- ENTRY QUALITY ---------------------------------------------------- #
    signal_bar_open_time_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    signal_close_time_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    entry_delay_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_slippage_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    signal_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    setup_strength: Mapped[float | None] = mapped_column(Float, nullable=True)
    council_bias: Mapped[str | None] = mapped_column(String(16), nullable=True)
    council_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    council_status: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # --- RISK PLAN ---------------------------------------------------------#
    risk_amount: Mapped[float | None] = mapped_column(Float, nullable=True)  # qty * |entry - stop| (position stop)
    planned_risk_amount: Mapped[float | None] = mapped_column(Float, nullable=True)  # the entry order's risk_amount
    expected_r: Mapped[float | None] = mapped_column(Float, nullable=True)
    planned_stop_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    planned_tp_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    leverage: Mapped[float] = mapped_column(Float, nullable=False)
    position_notional: Mapped[float] = mapped_column(Float, nullable=False)

    # --- EXCURSIONS (replay over market_candles; inclusive of the exit bar) --#
    mfe_price: Mapped[float] = mapped_column(Float, nullable=False)
    mae_price: Mapped[float] = mapped_column(Float, nullable=False)
    mfe_time_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mae_time_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    time_to_mfe_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    time_to_mae_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    mfe_r: Mapped[float | None] = mapped_column(Float, nullable=True)   # None when the stop is unknown (no R basis)
    mae_r: Mapped[float | None] = mapped_column(Float, nullable=True)
    mfe_bps: Mapped[float] = mapped_column(Float, nullable=False)
    mae_bps: Mapped[float] = mapped_column(Float, nullable=False)
    max_unrealized_profit: Mapped[float] = mapped_column(Float, nullable=False)  # >= 0
    max_unrealized_loss: Mapped[float] = mapped_column(Float, nullable=False)    # <= 0
    # tri-state: True = +0.25R reached before -0.8R; False = adverse first; None = neither / no R basis
    mfe_before_mae: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # --- EXIT QUALITY ------------------------------------------------------#
    exit_delay_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_slippage_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    post_exit_mfe_bps_30: Mapped[float | None] = mapped_column(Float, nullable=True)
    post_exit_mae_bps_30: Mapped[float | None] = mapped_column(Float, nullable=True)
    left_on_table_r: Mapped[float | None] = mapped_column(Float, nullable=True)

    trade_quality_class: Mapped[str] = mapped_column(String(32), nullable=False)
    regime_episode_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- REPLAY CROSS-CHECK vs positions.peak_price/trough_price ------------#
    # True = replay over [entry_bar, exit_bar) reproduces the persisted extreme;
    # False = a data-integrity finding (reported, never hidden); NULL = not
    # computable (e.g. no candles in the window).
    peak_crosscheck_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    trough_crosscheck_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    computation_version: Mapped[str] = mapped_column(String(16), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)


class StrategyRegimeMatrix(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "strategy_regime_matrix"
    __table_args__ = (
        Index("uq_srm_cell", "window_key", "granularity", "dim_id", "regime", unique=True),
        Index("ix_srm_dim", "granularity", "dim_id"),
    )

    window_key: Mapped[str] = mapped_column(String(16), nullable=False)      # full | 24h | 7d
    granularity: Mapped[str] = mapped_column(String(16), nullable=False)     # family | version | agent
    dim_id: Mapped[str] = mapped_column(String(64), nullable=False)           # family name / version id / agent id
    dim_label: Mapped[str | None] = mapped_column(String(64), nullable=True)  # display convenience only
    regime: Mapped[str] = mapped_column(String(32), nullable=False)

    trade_count: Mapped[int] = mapped_column(Integer, nullable=False)
    win_count: Mapped[int] = mapped_column(Integer, nullable=False)
    loss_count: Mapped[int] = mapped_column(Integer, nullable=False)
    win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    win_rate_ci_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    win_rate_ci_high: Mapped[float | None] = mapped_column(Float, nullable=True)

    gross_pnl: Mapped[float] = mapped_column(Float, nullable=False)
    fees: Mapped[float] = mapped_column(Float, nullable=False)
    funding: Mapped[float] = mapped_column(Float, nullable=False)
    slippage: Mapped[float] = mapped_column(Float, nullable=False)
    net_pnl: Mapped[float] = mapped_column(Float, nullable=False)
    avg_trade_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    expectancy: Mapped[float | None] = mapped_column(Float, nullable=True)
    expectancy_ci_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    expectancy_ci_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit_factor: Mapped[float | None] = mapped_column(Float, nullable=True)  # uncapped; None = no losses
    avg_winner: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_loser: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_holding_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_drawdown_currency: Mapped[float] = mapped_column(Float, nullable=False)

    mfe_r_mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    mfe_r_median: Mapped[float | None] = mapped_column(Float, nullable=True)
    mfe_r_p90: Mapped[float | None] = mapped_column(Float, nullable=True)
    mae_r_mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    mae_r_median: Mapped[float | None] = mapped_column(Float, nullable=True)
    mae_r_p90: Mapped[float | None] = mapped_column(Float, nullable=True)

    tp_first_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    sl_first_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    reversal_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_eaten_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    episode_count: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_state: Mapped[str] = mapped_column(String(12), nullable=False)   # UNTESTED | PROVISIONAL | TESTED
    under_sampled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    gross_edge: Mapped[bool] = mapped_column(Boolean, nullable=False)
    net_edge: Mapped[bool] = mapped_column(Boolean, nullable=False)

    computation_version: Mapped[str] = mapped_column(String(16), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)


class FitnessForwardPerformance(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "fitness_forward_performance"
    __table_args__ = (
        Index("uq_ffp_agent_asof_horizon", "agent_id", "as_of", "horizon_minutes", unique=True),
        Index("ix_ffp_asof_horizon", "as_of", "horizon_minutes"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    snapshot_source: Mapped[str] = mapped_column(String(16), nullable=False)  # recorded | reconstructed
    as_of: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    fitness_at_t: Mapped[float] = mapped_column(Float, nullable=False)
    fitness_components_at_t: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    horizon_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    window_start: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    window_end_planned: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    window_end_actual: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    censor_reason: Mapped[str] = mapped_column(String(24), nullable=False)  # none|agent_death|generation_rollover|data_end
    window_coverage: Mapped[float] = mapped_column(Float, nullable=False)   # actual/planned, 0..1

    future_trade_count: Mapped[int] = mapped_column(Integer, nullable=False)
    future_net_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    future_net_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    future_expectancy: Mapped[float | None] = mapped_column(Float, nullable=True)
    future_win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    future_max_drawdown_currency: Mapped[float | None] = mapped_column(Float, nullable=True)

    computation_version: Mapped[str] = mapped_column(String(16), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)


class ImmutableAnalyticsRecordError(RuntimeError):
    pass


# fitness_forward_performance is EVIDENCE, not a cache: recomputing a row with knowledge that
# did not exist at T would defeat the study. Insert-only at the ORM level too (the DB triggers
# in the migration are the authority; this fails fast under create_all, e.g. the test suite).
@event.listens_for(FitnessForwardPerformance, "before_update")
def _ffp_is_write_once(mapper, connection, target):
    raise ImmutableAnalyticsRecordError("fitness_forward_performance rows are write-once evidence and can never be updated")


@event.listens_for(FitnessForwardPerformance, "before_delete")
def _ffp_never_delete(mapper, connection, target):
    raise ImmutableAnalyticsRecordError("fitness_forward_performance rows are write-once evidence and can never be deleted")