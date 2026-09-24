"""Orders, positions, and trades — all scoped to a single agent."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Enum as SAEnum
from sqlalchemy import JSON, BigInteger, Boolean, Float, ForeignKey, Integer, String, UniqueConstraint, Uuid, Index, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin
from app.models.enums import ExecutionVenue, OrderStatus, Side, StrategyStage


class Order(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_agent_created", "agent_id", "created_at"),
        Index("ix_orders_status", "status"),
        Index("ix_orders_decision", "decision_id"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    # Orders <-> Decisions is a logical circular reference (Order references
    # the Decision that spawned it; Decision.order_id is filled in afterward
    # once execution completes). Only this side carries a real FK constraint
    # — see the matching comment on Decision.order_id in decision.py.
    decision_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("decisions.id"), nullable=True
    )

    # Idempotency key so a network retry can never duplicate an order
    # (spec section 41). Callers must derive this deterministically from
    # (agent_id, decision_id, attempt) rather than random.
    client_order_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)

    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[Side] = mapped_column(SAEnum(Side, name="order_side_enum"), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    requested_notional: Mapped[float | None] = mapped_column(Float, nullable=True)
    approved_notional: Mapped[float | None] = mapped_column(Float, nullable=True)
    initial_margin: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    requested_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    leverage: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)

    venue: Mapped[ExecutionVenue] = mapped_column(SAEnum(ExecutionVenue, name="execution_venue_enum"), nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        SAEnum(OrderStatus, name="order_status_enum"), default=OrderStatus.PENDING, nullable=False
    )
    rejection_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)

    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    filled_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    # ExecutionResult.latency_ms is returned by every adapter but was
    # previously discarded — persisting it is what lets stage_metrics_service
    # report avg_latency_ms per stage for the reality gap.
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    raw_venue_response: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    # Fill quality (spec: paper realism). `filled_quantity` < `quantity` on a
    # partial fill; `reduce_only` marks exits; `order_kind` is
    # market|stop|take_profit|liquidation.
    filled_quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    filled_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    fee: Mapped[float | None] = mapped_column(Float, nullable=True)
    slippage_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    reduce_only: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    order_kind: Mapped[str] = mapped_column(String(16), default="market", nullable=False)

    # Next-bar-open execution (paper): an entry decided on the CLOSE of bar N is persisted as a PENDING order and
    # filled at the OPEN of bar N+1 - exactly the backtest's model, with no signal-bar look-ahead. `intent` carries
    # what the fill needs from the signal bar (ATR, swing levels, regime, sizing method); an order that was not
    # filled on bar N+1 is CANCELLED, never filled late.
    signal_candle_open_time: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    intent: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class Position(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "positions"
    __table_args__ = (
        Index("ix_positions_agent_open", "agent_id", "is_open"),
        # DB-level "one open position per agent": the final barrier against a
        # duplicate entry regardless of what any Python check believed.
        Index(
            "uq_position_one_open_per_agent", "agent_id", unique=True,
            sqlite_where=text("is_open = 1"), postgresql_where=text("is_open"),
        ),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[Side] = mapped_column(SAEnum(Side, name="position_side_enum"), nullable=False)

    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    leverage: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    initial_margin: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    maintenance_margin: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    peak_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    trough_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_funding_time: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    # Cost basis carried to the closing Trade so realized PnL includes the
    # entry fee, entry slippage and every funding settlement.
    entry_order_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("orders.id"), nullable=True)
    entry_fee: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    entry_slippage_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    funding_accrued: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    liquidation_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_candle_open_time: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    entry_regime: Mapped[str | None] = mapped_column(String(32), nullable=True)
    trailing_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    stop_loss_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    trailing_stop_distance: Mapped[float | None] = mapped_column(Float, nullable=True)

    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    is_open: Mapped[bool] = mapped_column(default=True, nullable=False)
    # Which execution venue opened this position (PAPER / SHADOW / LIVE). Switching TRADING_MODE with positions open on
    # another venue would mix books, so new entries are refused until they close (see run_decision_cycle).
    venue: Mapped[ExecutionVenue] = mapped_column(
        SAEnum(ExecutionVenue, name="execution_venue_enum"), default=ExecutionVenue.PAPER, nullable=False,
        server_default=ExecutionVenue.PAPER.value,
    )

    # A signal exit decided on the close of bar N executes at the open of bar N+1 (paper next-open model).
    pending_exit_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pending_exit_signal_time: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Newest bar whose OHLC this position has been managed against. Makes protective processing idempotent per
    # bar (a retried cycle or a protective replay never evaluates - or extends the trailing extreme with - a bar twice).
    last_processed_open_time: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Consecutive failed attempts to close this position (drives the deterministic force-settle fallback).
    exit_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")

    opened_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Trade(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A closed round-trip (or partial close) — the unit fitness/metrics are
    computed over. Distinct from Order: one position close may realize a
    Trade even if it resulted from multiple fills."""

    __tablename__ = "trades"
    __table_args__ = (
        Index("ix_trades_agent_closed", 'agent_id', 'closed_at'),
        Index("ix_trades_closed_at", 'closed_at'),
        Index("ix_trades_stage", 'stage'),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    position_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("positions.id"), nullable=False)
    entry_order_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("orders.id"), nullable=True)
    exit_order_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("orders.id"), nullable=True)

    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[Side] = mapped_column(SAEnum(Side, name="trade_side_enum"), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)

    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    exit_price: Mapped[float] = mapped_column(Float, nullable=False)

    gross_pnl: Mapped[float] = mapped_column(Float, nullable=False)
    fees: Mapped[float] = mapped_column(Float, nullable=False)
    funding: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    slippage_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    net_pnl: Mapped[float] = mapped_column(Float, nullable=False)
    bad_debt: Mapped[float] = mapped_column(Float, default=0.0, nullable=False, server_default="0")

    opened_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    closed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    holding_seconds: Mapped[int] = mapped_column(Integer, nullable=False)

    entry_regime: Mapped[str | None] = mapped_column(String(32), nullable=True)
    exit_regime: Mapped[str | None] = mapped_column(String(32), nullable=True)
    exit_reason: Mapped[str] = mapped_column(String(64), nullable=False)  # stop_loss|take_profit|signal|liquidation|manual

    # Which StrategyStage was active on the parent StrategyVersion when this
    # trade closed. StrategyVersion.stage is mutable (advances over time), so
    # without stamping it here, stage_metrics_service.compute_live_stage_metrics
    # can't tell a PAPER-stage trade apart from a SHADOW-stage one for the
    # same version — this column is what makes that split possible.
    stage: Mapped[StrategyStage | None] = mapped_column(
        SAEnum(StrategyStage, name="trade_stage_enum"), nullable=True
    )


class FundingPayment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One funding settlement charged to (or credited to) one position. The
    (position, settlement time) unique constraint makes accrual idempotent:
    a retried cycle can never charge the same settlement twice."""

    __tablename__ = "funding_payments"
    __table_args__ = (
        UniqueConstraint("position_id", "funding_time_ms", name="uq_funding_payment_position_time"),
        Index("ix_funding_payments_agent", "agent_id"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    position_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("positions.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    funding_time_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    funding_rate: Mapped[float] = mapped_column(Float, nullable=False)
    position_notional: Mapped[float] = mapped_column(Float, nullable=False)
    payment: Mapped[float] = mapped_column(Float, nullable=False)  # + = agent paid, - = agent received
