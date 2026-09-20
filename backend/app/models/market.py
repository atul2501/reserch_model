"""Market data, feature, and regime tables.

One row per (symbol, timeframe, timestamp) — this is the single shared
pipeline that feeds all 500 agents (spec section 6/7). Agents never fetch
market data themselves.
"""
from __future__ import annotations

import uuid

from sqlalchemy import Enum as SAEnum
from sqlalchemy import BigInteger, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import MarketRegime


class MarketCandle(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "market_candles"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "open_time", name="uq_candle_symbol_tf_time"),
        Index("ix_candle_symbol_tf_time", "symbol", "timeframe", "open_time"),
    )

    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    open_time: Mapped[int] = mapped_column(BigInteger, nullable=False)  # unix ms, UTC
    close_time: Mapped[int] = mapped_column(BigInteger, nullable=False)

    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)

    trade_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    funding_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    open_interest: Mapped[float | None] = mapped_column(Float, nullable=True)

    is_final: Mapped[bool] = mapped_column(default=True, nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="hyperliquid", nullable=False)


class MarketFeatureSet(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Computed feature vector for one candle close — the shared market
    context every agent and council analyst consumes (spec section 4)."""

    __tablename__ = "market_features"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "candle_open_time", name="uq_features_symbol_tf_time"),
        Index("ix_features_symbol_tf_time", "symbol", "timeframe", "candle_open_time"),
    )

    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    candle_open_time: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Full computed feature vector (trend/momentum/volatility/structure/
    # volume/price-action — see feature_engine.py for the schema this fills).
    features: Mapped[dict] = mapped_column(JSONB, nullable=False)


class MarketRegimeRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "market_regimes"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "candle_open_time", name="uq_regime_symbol_tf_time"),
        Index("ix_regime_symbol_tf_time", "symbol", "timeframe", "candle_open_time"),
    )

    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    candle_open_time: Mapped[int] = mapped_column(BigInteger, nullable=False)

    regime: Mapped[MarketRegime] = mapped_column(SAEnum(MarketRegime, name="market_regime_enum"), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    detector_version: Mapped[str] = mapped_column(String(16), default="v1", nullable=False)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
