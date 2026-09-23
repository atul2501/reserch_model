"""MarketDataService — the single shared market-data pipeline (spec 6).

500 agents never fetch market data themselves. This service is the only
writer of `market_candles`/`funding_rates`, and the only reader of
`HyperliquidClient`. It provides:

  - `sync_recent_candles` / `upsert_candles`: idempotent upsert of candles
    (REST poll or WebSocket push share the same path)
  - candle finality: a bar is `is_final` only once its close time is at least
    `candle_finality_grace_ms` in the past. Trading code reads confirmed bars
    only; the open (mutable) bar is available to display callers only.
  - gap detection + REST backfill + continuity validation. An unrecoverable
    hole raises the durable `data_gap_halt` flag, which the Risk Engine turns
    into "no NEW entries" — the system never trades through an unknown gap.
  - `sync_funding_history`: exchange-published hourly funding settlements.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import metrics
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.system_flags import DATA_GAP_HALT, active_flags, set_flag
from app.market.hyperliquid_client import HyperliquidClient
from app.models.market import FundingRate, MarketCandle

logger = get_logger(__name__)

STALE_DATA_THRESHOLD_SECONDS = 180  # legacy default; runtime value comes from settings

_CANDLE_COLUMNS = ["open_time", "open", "high", "low", "close", "volume", "funding_rate", "open_interest"]


@dataclass
class GapReport:
    missing_before: list[int] = field(default_factory=list)
    missing_after: list[int] = field(default_factory=list)
    backfilled: int = 0
    halted: bool = False

    @property
    def recovered(self) -> bool:
        return not self.missing_after


def _dialect_insert(db: AsyncSession):
    name = db.get_bind().dialect.name
    return postgresql.insert if name == "postgresql" else sqlite.insert


def _as_float(value: object) -> float | None:
    try:
        return float(value) if value is not None else None  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


class MarketDataService:
    def __init__(self, client: HyperliquidClient | None = None, *, clock_ms=None) -> None:
        settings = get_settings()
        self._settings = settings
        self._client = client or HyperliquidClient()
        self._symbol = settings.market_symbol
        self._timeframe = settings.market_timeframe
        # Injectable clock (unix ms) so exact-boundary behaviour is testable.
        self._clock_ms = clock_ms or HyperliquidClient.now_ms

    @property
    def interval_ms(self) -> int:
        return HyperliquidClient.timeframe_to_ms(self._timeframe)

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ #
    # Writes
    # ------------------------------------------------------------------ #
    def is_confirmed(self, close_time_ms: int, now_ms: int | None = None) -> bool:
        """Finality rule shared by REST and WebSocket ingestion."""
        now_ms = self._clock_ms() if now_ms is None else now_ms
        return int(close_time_ms) + self._settings.candle_finality_grace_ms <= now_ms

    async def sync_recent_candles(
        self, db: AsyncSession, lookback_candles: int = 500, *, with_funding_context: bool = True
    ) -> int:
        """Fetches the last `lookback_candles` candles and upserts them.
        Returns the number of rows written. Idempotent (spec 6)."""
        interval_ms = self.interval_ms
        end_ms = self._clock_ms()
        start_ms = end_ms - interval_ms * lookback_candles

        t_fetch = time.monotonic()
        raw = await self._client.get_candles(self._symbol, self._timeframe, start_ms, end_ms)
        metrics.observe("market_data_latency_seconds", time.monotonic() - t_fetch)
        if not raw:
            logger.warning("market_data.empty_response", symbol=self._symbol)
            metrics.inc("market_data_empty_responses")
            return 0

        funding_context: dict = {}
        if with_funding_context:
            try:
                funding_context = await self._client.get_meta_and_funding(self._symbol)
            except Exception as exc:  # funding context is informational only
                logger.warning("market_data.funding_context_unavailable", error=str(exc))

        return await self.upsert_candles(db, raw, now_ms=end_ms, funding_context=funding_context)

    async def upsert_candles(
        self, db: AsyncSession, raw: list[dict], *, now_ms: int | None = None, funding_context: dict | None = None
    ) -> int:
        """Idempotent upsert of raw Hyperliquid candle dicts (REST or WS)."""
        if not raw:
            return 0
        now_ms = self._clock_ms() if now_ms is None else now_ms
        funding_context = funding_context or {}
        raw = sorted(raw, key=lambda c: int(c["t"]))

        newest_final_open = max(
            (int(c["t"]) for c in raw if self.is_confirmed(int(c["T"]), now_ms)), default=None
        )
        funding_rate = _as_float(funding_context.get("funding"))
        open_interest = _as_float(funding_context.get("openInterest"))

        rows = []
        for c in raw:
            final = self.is_confirmed(int(c["T"]), now_ms)
            latest = final and int(c["t"]) == newest_final_open
            rows.append(
                {
                    "symbol": self._symbol,
                    "timeframe": self._timeframe,
                    "open_time": int(c["t"]),
                    "close_time": int(c["T"]),
                    "open": float(c["o"]),
                    "high": float(c["h"]),
                    "low": float(c["l"]),
                    "close": float(c["c"]),
                    "volume": float(c["v"]),
                    "trade_count": int(c.get("n", 0)) or None,
                    "is_final": final,
                    # Point-in-time exchange values are attributed only to the
                    # newest confirmed bar; older rows keep whatever they had.
                    # Funding ACCRUAL never reads this column (see FundingRate).
                    "funding_rate": funding_rate if latest else None,
                    "open_interest": open_interest if latest else None,
                    "source": "hyperliquid",
                }
            )

        await self._log_revised_final_candles(db, rows)

        insert = _dialect_insert(db)
        stmt = insert(MarketCandle).values(rows)
        update_cols = {
            col: getattr(stmt.excluded, col)
            for col in ("close_time", "open", "high", "low", "close", "volume", "trade_count", "is_final")
        }
        # Never blank out (or rewrite) previously stored funding/OI context.
        update_cols["funding_rate"] = func.coalesce(stmt.excluded.funding_rate, MarketCandle.funding_rate)
        update_cols["open_interest"] = func.coalesce(stmt.excluded.open_interest, MarketCandle.open_interest)
        # A confirmed bar never reverts to "open" (guards out-of-order pushes).
        update_cols["is_final"] = MarketCandle.is_final | stmt.excluded.is_final
        stmt = stmt.on_conflict_do_update(index_elements=["symbol", "timeframe", "open_time"], set_=update_cols)
        await db.execute(stmt)
        await db.commit()
        return len(rows)

    async def _log_revised_final_candles(self, db: AsyncSession, rows: list[dict]) -> None:
        """A confirmed bar whose OHLCV later changes means a decision may have
        been computed on data that was not yet final. Rare by construction
        (grace period) — but it must be visible, not silent."""
        finals = [r for r in rows if r["is_final"]]
        if not finals:
            return
        existing = (
            await db.execute(
                select(MarketCandle).where(
                    MarketCandle.symbol == self._symbol,
                    MarketCandle.timeframe == self._timeframe,
                    MarketCandle.is_final.is_(True),
                    MarketCandle.open_time.in_([r["open_time"] for r in finals]),
                )
            )
        ).scalars().all()
        by_time = {c.open_time: c for c in existing}
        for r in finals:
            old = by_time.get(r["open_time"])
            if old is None:
                continue
            if any(abs(getattr(old, k) - r[k]) > 1e-9 for k in ("open", "high", "low", "close", "volume")):
                logger.error("market_data.final_candle_revised", open_time=r["open_time"], symbol=self._symbol)

    async def sync_funding_history(self, db: AsyncSession) -> int:
        """Upserts exchange-published funding settlements for accrual."""
        start_ms = self._clock_ms() - self._settings.funding_history_lookback_hours * 3_600_000
        try:
            raw = await self._client.get_funding_history(self._symbol, start_ms)
        except Exception as exc:
            logger.warning("market_data.funding_history_unavailable", error=str(exc))
            return 0
        rows = [
            {
                "symbol": self._symbol,
                "time_ms": int(item["time"]),
                "rate": float(item["fundingRate"]),
                "premium": _as_float(item.get("premium")),
            }
            for item in raw
            if item.get("time") is not None and item.get("fundingRate") is not None
        ]
        if not rows:
            return 0
        insert = _dialect_insert(db)
        stmt = insert(FundingRate).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "time_ms"],
            set_={"rate": stmt.excluded.rate, "premium": stmt.excluded.premium},
        )
        await db.execute(stmt)
        await db.commit()
        return len(rows)

    async def backfill_history(self, db: AsyncSession, start_ms: int, end_ms: int, *, page_bars: int = 4000) -> int:
        """Pages REST candleSnapshot over [start_ms, end_ms] (research warm-up /
        long-outage recovery). Idempotent; returns rows written."""
        step = self.interval_ms * page_bars
        total = 0
        cursor = start_ms
        while cursor < end_ms:
            raw = await self._client.get_candles(self._symbol, self._timeframe, cursor, min(end_ms, cursor + step))
            total += await self.upsert_candles(db, raw)
            cursor += step
        return total

    # ------------------------------------------------------------------ #
    # Gap detection / recovery
    # ------------------------------------------------------------------ #
    async def detect_gaps(self, db: AsyncSession, window: int | None = None) -> list[int]:
        """Open-times missing from the trailing `window` confirmed bars."""
        window = window or self._settings.gap_check_window_bars
        open_times = (
            await db.execute(
                select(MarketCandle.open_time)
                .where(
                    MarketCandle.symbol == self._symbol,
                    MarketCandle.timeframe == self._timeframe,
                    MarketCandle.is_final.is_(True),
                )
                .order_by(MarketCandle.open_time.desc())
                .limit(window)
            )
        ).scalars().all()
        if len(open_times) < 2:
            return []
        present = set(open_times)
        step = self.interval_ms
        lo, hi = min(present), max(present)
        return [t for t in range(lo, hi + 1, step) if t not in present]

    async def recover_gaps(self, db: AsyncSession) -> GapReport:
        """Detect -> REST backfill -> re-validate -> persist -> resume/halt.

        On success the `data_gap_halt` flag is cleared; if any bar is still
        missing afterwards the flag is raised (NEW entries blocked; exits and
        risk management keep running)."""
        report = GapReport(missing_before=await self.detect_gaps(db))
        if report.missing_before:
            step = self.interval_ms
            start, end = min(report.missing_before), max(report.missing_before) + step
            logger.warning("market_data.gap_detected", missing=len(report.missing_before), first=start, last=end - step)
            try:
                raw = await self._client.get_candles(self._symbol, self._timeframe, start, end)
                report.backfilled = await self.upsert_candles(db, raw)
            except Exception as exc:
                logger.error("market_data.gap_backfill_failed", error=str(exc))
            report.missing_after = await self.detect_gaps(db)
        else:
            report.missing_after = []

        currently_halted = DATA_GAP_HALT in await active_flags(db)
        if report.missing_after:
            report.halted = True
            await set_flag(
                db, DATA_GAP_HALT, True,
                reason=f"{len(report.missing_after)} unrecovered candle(s), first={report.missing_after[0]}",
                set_by="market_data_service",
            )
            await db.commit()
            logger.error("market_data.gap_unrecovered_trading_halted", missing=len(report.missing_after))
        elif currently_halted:
            await set_flag(db, DATA_GAP_HALT, False, reason=None, set_by="market_data_service")
            await db.commit()
            logger.info("market_data.gap_recovered_trading_resumed", backfilled=report.backfilled)
        return report

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    async def get_recent_candles(
        self,
        db: AsyncSession,
        limit: int = 300,
        *,
        confirmed_only: bool = True,
        up_to_open_time: int | None = None,
    ) -> pd.DataFrame:
        """Oldest-to-newest candles. Trading callers use the default
        (confirmed only); the mutable open bar is for explicitly labelled
        display/recovery callers. `up_to_open_time` bounds the frame at a
        specific confirmed bar (catch-up replay / point-in-time features)."""
        stmt = (
            select(MarketCandle)
            .where(MarketCandle.symbol == self._symbol, MarketCandle.timeframe == self._timeframe)
            .order_by(MarketCandle.open_time.desc())
            .limit(limit)
        )
        if confirmed_only:
            stmt = stmt.where(MarketCandle.is_final.is_(True))
        if up_to_open_time is not None:
            stmt = stmt.where(MarketCandle.open_time <= up_to_open_time)
        candles = list(reversed((await db.execute(stmt)).scalars().all()))
        if not candles:
            return pd.DataFrame(columns=_CANDLE_COLUMNS)
        return pd.DataFrame(
            [
                {
                    "open_time": c.open_time,
                    "open": c.open,
                    "high": c.high,
                    "low": c.low,
                    "close": c.close,
                    "volume": c.volume,
                    "funding_rate": c.funding_rate,
                    "open_interest": c.open_interest,
                }
                for c in candles
            ]
        )

    async def latest_confirmed_open_time(self, db: AsyncSession) -> int | None:
        return (
            await db.execute(
                select(func.max(MarketCandle.open_time)).where(
                    MarketCandle.symbol == self._symbol,
                    MarketCandle.timeframe == self._timeframe,
                    MarketCandle.is_final.is_(True),
                )
            )
        ).scalar_one_or_none()

    async def confirmed_open_times_after(self, db: AsyncSession, after_open_time: int, limit: int) -> list[int]:
        rows = (
            await db.execute(
                select(MarketCandle.open_time)
                .where(
                    MarketCandle.symbol == self._symbol,
                    MarketCandle.timeframe == self._timeframe,
                    MarketCandle.is_final.is_(True),
                    MarketCandle.open_time > after_open_time,
                )
                .order_by(MarketCandle.open_time.asc())
                .limit(limit)
            )
        ).scalars().all()
        return list(rows)

    async def wait_for_confirmed_candle(
        self, db: AsyncSession, target_open_time: int, *, deadline_seconds: float | None = None
    ) -> bool:
        """After a candle boundary, poll until the exchange has published the
        closed bar `target_open_time` (bounded). Replaces "sleep +0.25s and
        hope", which silently skipped bars the exchange published late."""
        deadline = time.monotonic() + (
            self._settings.candle_wait_deadline_seconds if deadline_seconds is None else deadline_seconds
        )
        while True:
            latest = await self.latest_confirmed_open_time(db)
            if latest is not None and latest >= target_open_time:
                return True
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(self._settings.candle_poll_interval_seconds)
            try:
                await self.sync_recent_candles(db, lookback_candles=10, with_funding_context=False)
            except Exception as exc:
                logger.warning("market_data.poll_failed", error=str(exc))

    async def latest_candle_age_seconds(self, db: AsyncSession) -> float | None:
        close_time = (
            await db.execute(
                select(MarketCandle.close_time)
                .where(
                    MarketCandle.symbol == self._symbol,
                    MarketCandle.timeframe == self._timeframe,
                    MarketCandle.is_final.is_(True),
                )
                .order_by(MarketCandle.open_time.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if close_time is None:
            return None
        return self._clock_ms() / 1000 - close_time / 1000

    async def is_stale(self, db: AsyncSession) -> bool:
        age = await self.latest_candle_age_seconds(db)
        if age is None:
            return True
        return age > self._settings.data_stale_threshold_seconds
