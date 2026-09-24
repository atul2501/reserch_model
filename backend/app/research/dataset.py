"""Research datasets: load confirmed candles, fingerprint them, freeze them
into chronologically-split epochs (TRAIN / VALIDATION / FINAL-OOS)."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

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


class EpochIntegrityError(RuntimeError):
    """The candles now stored for a sealed epoch no longer match what was sealed (missing or revised bars)."""


class NoActiveEpochError(RuntimeError):
    pass


def _oos_fingerprint(oos_slice: pd.DataFrame, bounds: tuple[int, int, int, int]) -> str:
    """Fingerprint of the sealed holdout: the OOS candles PLUS the chronological boundaries. Independent of anything
    that happens to the market after the seal, so it is stable for the epoch's whole life."""
    h = hashlib.sha256()
    h.update(np.ascontiguousarray(oos_slice[_COLS].to_numpy(dtype="<f8")).tobytes())
    h.update(("|".join(str(b) for b in bounds)).encode())
    return h.hexdigest()


async def get_active_epoch(db: AsyncSession, symbol: str, timeframe: str) -> ResearchEpoch | None:
    return (
        await db.execute(
            select(ResearchEpoch).where(
                ResearchEpoch.symbol == symbol, ResearchEpoch.timeframe == timeframe, ResearchEpoch.active.is_(True)
            ).order_by(ResearchEpoch.created_at.desc()).limit(1)
        )
    ).scalars().first()


def _build_epoch(candles: pd.DataFrame, *, symbol: str, timeframe: str, train_fraction: float, validation_fraction: float,
                 reason: str, supersedes: str | None) -> ResearchEpoch:
    n = len(candles)
    oos_n = max(1, round(n * (1.0 - train_fraction - validation_fraction)))
    pre = candles.iloc[: n - oos_n]
    oos = candles.iloc[n - oos_n:]
    if len(pre) < 2 or len(oos) < 1:
        raise ValueError("not enough candles to seal a train/validation/OOS epoch")
    train_n = int(len(pre) * train_fraction / (train_fraction + validation_fraction))
    train_end_ms = int(pre["open_time"].iloc[max(0, train_n - 1)])
    validation_end_ms = int(pre["open_time"].iloc[-1])
    oos_start_ms, oos_end_ms = int(oos["open_time"].iloc[0]), int(oos["open_time"].iloc[-1])
    start_ms = int(candles["open_time"].iloc[0])
    bounds = (start_ms, train_end_ms, validation_end_ms, oos_end_ms)
    fp = _oos_fingerprint(oos, bounds)
    return ResearchEpoch(
        epoch_id=f"EPOCH-{fp[:12]}", symbol=symbol, timeframe=timeframe, start_ms=start_ms, end_ms=oos_end_ms,
        n_candles=n, dataset_fingerprint=fp, train_end_ms=train_end_ms, validation_end_ms=validation_end_ms,
        oos_locked=True, oos_start_ms=oos_start_ms, oos_end_ms=oos_end_ms, oos_fingerprint=fp, active=True,
        sealed_at=datetime.now(timezone.utc), renewal_reason=reason, supersedes_epoch_id=supersedes,
    )


async def seal_epoch(
    db: AsyncSession, candles: pd.DataFrame, *, symbol: str, timeframe: str, reason: str = "initial",
    train_fraction: float | None = None, validation_fraction: float | None = None, supersedes: str | None = None,
) -> ResearchEpoch:
    """Freezes `candles` as an epoch: TRAIN and VALIDATION strictly before a fixed, sealed OOS range. The OOS range,
    its fingerprint and the boundaries never change afterwards (DB triggers + ORM guard), no matter how many candles
    arrive later."""
    s = get_settings()
    epoch = _build_epoch(
        candles, symbol=symbol, timeframe=timeframe,
        train_fraction=train_fraction if train_fraction is not None else s.research_train_fraction,
        validation_fraction=validation_fraction if validation_fraction is not None else s.research_validation_fraction,
        reason=reason, supersedes=supersedes,
    )
    existing = (await db.execute(select(ResearchEpoch).where(ResearchEpoch.dataset_fingerprint == epoch.dataset_fingerprint))).scalar_one_or_none()
    if existing is not None:
        return existing
    db.add(epoch)
    await db.flush()
    return epoch


async def get_or_create_epoch(
    db: AsyncSession, candles: pd.DataFrame, *, symbol: str, timeframe: str,
    train_fraction: float | None = None, validation_fraction: float | None = None,
) -> tuple[ResearchEpoch, bool]:
    """The ACTIVE sealed epoch if there is one (whatever `candles` the caller happens to hold now - the holdout does not
    move as data arrives); otherwise seal one from `candles`. Returns (epoch, created)."""
    active = await get_active_epoch(db, symbol, timeframe)
    if active is not None:
        return active, False
    epoch = await seal_epoch(db, candles, symbol=symbol, timeframe=timeframe, reason="initial",
                             train_fraction=train_fraction, validation_fraction=validation_fraction)
    return epoch, True


async def renew_epoch(
    db: AsyncSession, candles: pd.DataFrame, *, symbol: str, timeframe: str, reason: str,
) -> ResearchEpoch:
    """The ONLY way a holdout is replaced: an explicit, reasoned operator action. The old epoch is superseded (kept
    forever, still queryable, its OOS evaluations untouched); the new one is sealed from `candles`."""
    if not reason or not reason.strip():
        raise ValueError("renewing the OOS epoch requires a reason (it is recorded permanently)")
    old = await get_active_epoch(db, symbol, timeframe)
    epoch = await seal_epoch(db, candles, symbol=symbol, timeframe=timeframe, reason=reason.strip()[:256],
                             supersedes=old.epoch_id if old is not None else None)
    if old is not None and old.id != epoch.id:
        old.active = False
        old.superseded_at = datetime.now(timezone.utc)
        await db.flush()
    return epoch


async def load_epoch_candles(db: AsyncSession, epoch: ResearchEpoch) -> pd.DataFrame:
    """The epoch's frame, loaded by its FIXED bounds [start_ms, oos_end_ms] - so it is identical on every cycle and
    unaffected by new candles - and verified against the sealed fingerprint. Raises EpochIntegrityError if bars are
    missing or were revised: a holdout that changed under our feet must never be evaluated silently."""
    frame = await load_confirmed_candles(db, epoch.symbol, epoch.timeframe, start_ms=epoch.start_ms, end_ms=epoch.oos_end_ms)
    if len(frame) != epoch.n_candles:
        raise EpochIntegrityError(f"{epoch.epoch_id}: {len(frame)} confirmed candles found, {epoch.n_candles} were sealed")
    oos = frame[frame["open_time"] >= epoch.oos_start_ms]
    bounds = (epoch.start_ms, epoch.train_end_ms, epoch.validation_end_ms, epoch.oos_end_ms)
    if _oos_fingerprint(oos, bounds) != epoch.oos_fingerprint:
        raise EpochIntegrityError(f"{epoch.epoch_id}: the sealed OOS candles no longer match their fingerprint")
    return frame


def slice_train_validation(candles: pd.DataFrame, epoch: ResearchEpoch) -> pd.DataFrame:
    """The ONLY data evolution/fitness/selection may see: everything up to and
    including the validation boundary. The OOS slice is not reachable from here."""
    return candles[candles["open_time"] <= epoch.validation_end_ms].reset_index(drop=True)
