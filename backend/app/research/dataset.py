"""Research datasets: load confirmed candles, fingerprint them, freeze them
into chronologically-split epochs (TRAIN / VALIDATION / FINAL-OOS)."""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtesting.splits import chronological_split
from app.core.config import get_settings
from app.models.market import FundingRate, MarketCandle
from app.models.research import ResearchEpoch

_COLS = ["open_time", "open", "high", "low", "close", "volume"]


def fingerprint_frame(candles: pd.DataFrame) -> str:
    """sha256 over the ordered OHLCV of the frame (float64, little-endian) —
    identical data always yields the identical fingerprint."""
    arr = np.ascontiguousarray(candles[_COLS].to_numpy(dtype="<f8"))
    return hashlib.sha256(arr.tobytes()).hexdigest()


async def count_confirmed_candles(db: AsyncSession, symbol: str, timeframe: str) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(MarketCandle).where(
                MarketCandle.symbol == symbol, MarketCandle.timeframe == timeframe, MarketCandle.is_final.is_(True)
            )
        )
    ).scalar_one()


async def load_confirmed_candles(
    db: AsyncSession, symbol: str, timeframe: str, *, start_ms: int | None = None, end_ms: int | None = None,
    limit: int | None = None,
) -> pd.DataFrame:
    """Confirmed (is_final) candles only — research, like trading, never sees an open bar."""
    stmt = select(*[getattr(MarketCandle, c) for c in _COLS]).where(
        MarketCandle.symbol == symbol, MarketCandle.timeframe == timeframe, MarketCandle.is_final.is_(True)
    )
    if start_ms is not None:
        stmt = stmt.where(MarketCandle.open_time >= start_ms)
    if end_ms is not None:
        stmt = stmt.where(MarketCandle.open_time <= end_ms)
    if limit is not None:  # the most recent `limit`
        stmt = stmt.order_by(MarketCandle.open_time.desc()).limit(limit)
    else:
        stmt = stmt.order_by(MarketCandle.open_time.asc())
    rows = (await db.execute(stmt)).all()
    df = pd.DataFrame(rows, columns=_COLS)
    return df.sort_values("open_time").reset_index(drop=True) if len(df) else df


async def load_funding(db: AsyncSession, symbol: str, start_ms: int, end_ms: int) -> list[tuple[int, float]]:
    rows = (
        await db.execute(
            select(FundingRate.time_ms, FundingRate.rate)
            .where(FundingRate.symbol == symbol, FundingRate.time_ms >= start_ms, FundingRate.time_ms <= end_ms)
            .order_by(FundingRate.time_ms)
        )
    ).all()
    return [(int(t), float(r)) for t, r in rows]


async def get_or_create_epoch(
    db: AsyncSession, candles: pd.DataFrame, *, symbol: str, timeframe: str,
    train_fraction: float | None = None, validation_fraction: float | None = None,
) -> tuple[ResearchEpoch, bool]:
    """Freezes `candles` as a research epoch. The same data always maps to the
    same epoch (unique fingerprint), so its OOS slice can be consumed only once
    per strategy version no matter how often the pipeline is re-run."""
    s = get_settings()
    train_fraction = train_fraction if train_fraction is not None else s.research_train_fraction
    validation_fraction = validation_fraction if validation_fraction is not None else s.research_validation_fraction
    fp = fingerprint_frame(candles)
    existing = (await db.execute(select(ResearchEpoch).where(ResearchEpoch.dataset_fingerprint == fp))).scalar_one_or_none()
    if existing is not None:
        return existing, False
    split = chronological_split(candles, train_fraction=train_fraction, validation_fraction=validation_fraction)
    epoch = ResearchEpoch(
        epoch_id=f"EPOCH-{fp[:12]}", symbol=symbol, timeframe=timeframe,
        start_ms=int(candles["open_time"].iloc[0]), end_ms=int(candles["open_time"].iloc[-1]), n_candles=len(candles),
        dataset_fingerprint=fp,
        train_end_ms=int(split.train["open_time"].iloc[-1]),
        validation_end_ms=int(split.validation["open_time"].iloc[-1]),
        oos_locked=True,
    )
    db.add(epoch)
    await db.flush()
    return epoch, True


def slice_train_validation(candles: pd.DataFrame, epoch: ResearchEpoch) -> pd.DataFrame:
    """The ONLY data evolution/fitness/selection may see: everything up to and
    including the validation boundary. The OOS slice is not reachable from here."""
    return candles[candles["open_time"] <= epoch.validation_end_ms].reset_index(drop=True)
