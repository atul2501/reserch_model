"""One trading cycle per *confirmed* candle (spec section 61's pipeline):

    confirmed candle -> features -> regime -> council (cadence) -> shared
    context -> all agents (DNA) -> risk -> execution -> PnL -> extinction check

Invariants enforced here (each has a test in tests/test_worker_cycle.py):
  * only `is_final=True` candles are ever read for a decision;
  * a candle is processed at most once to completion (`worker_cycles.cycle_id`
    unique + per-agent decision unique constraint make a re-run idempotent);
  * a crash mid-cycle leaves the candle pending, not lost;
  * bars missed because a cycle overran are replayed in order with NEW ENTRIES
    disabled (exits/stops still evaluated on every bar);
  * an unrecovered data gap, kill switch, or stale data blocks NEW entries.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.decision_loop import run_decision_cycle
from app.agents.lifecycle import is_population_extinct, record_extinction
from app.core.config import get_settings
from app.core.logging import get_logger
from app.council.service import run_council_cycle
from app.execution.router import get_execution_engine
from app.market.feature_engine import MIN_CANDLES_REQUIRED, InsufficientDataError, compute_features
from app.market.market_data_service import MarketDataService
from app.models.market import MarketFeatureSet, MarketRegimeRecord
from app.models.strategy import Generation
from app.models.system import WorkerCycle
from app.schemas.market_context import MarketContext
from app.services.ollama_client import OllamaClient
from app.worker.scheduler import council_due

logger = get_logger(__name__)

COMPLETED = "COMPLETED"
STARTED = "STARTED"
FAILED = "FAILED"
FAILED_PERMANENT = "FAILED_PERMANENT"
SKIPPED_CATCHUP = "SKIPPED_CATCHUP"
_DONE_STATUSES = (COMPLETED, FAILED_PERMANENT, SKIPPED_CATCHUP)
MAX_CYCLE_ATTEMPTS = 3


@dataclass
class CycleOutcome:
    cycle_id: str
    candle_open_time: int
    status: str
    agents_processed: int = 0
    council_status: str = "NOT_RUN"
    halt_reason: str | None = None
    latency_seconds: float | None = None


def make_cycle_id(symbol: str, timeframe: str, open_time: int) -> str:
    return f"{symbol}:{timeframe}:{open_time}"


async def _last_done_open_time(db: AsyncSession) -> int | None:
    return (
        await db.execute(select(func.max(WorkerCycle.candle_timestamp)).where(WorkerCycle.status.in_(_DONE_STATUSES)))
    ).scalar_one_or_none()


async def pending_open_times(db: AsyncSession, market: MarketDataService) -> tuple[list[int], list[int]]:
    """Returns (to_process, to_skip). Cold start (no prior cycle) processes only
    the latest confirmed bar — history is never replayed into live decisions."""
    settings = get_settings()
    latest = await market.latest_confirmed_open_time(db)
    if latest is None:
        return [], []
    last_done = await _last_done_open_time(db)
    if last_done is None:
        return [latest], []
    pending = await market.confirmed_open_times_after(db, last_done, limit=10_000)
    if len(pending) <= settings.max_catchup_bars:
        return pending, []
    return pending[-settings.max_catchup_bars:], pending[:-settings.max_catchup_bars]


async def _record_skipped(db: AsyncSession, market: MarketDataService, open_times: list[int]) -> None:
    settings = get_settings()
    now = time.time()
    for ot in open_times:
        cid = make_cycle_id(settings.market_symbol, settings.market_timeframe, ot)
        existing = (await db.execute(select(WorkerCycle).where(WorkerCycle.cycle_id == cid))).scalar_one_or_none()
        if existing is None:
            db.add(WorkerCycle(
                cycle_id=cid, candle_timestamp=ot, cycle_started_at=now, cycle_completed_at=now,
                cycle_latency_seconds=0.0, completed=False, status=SKIPPED_CATCHUP,
                error="catch-up window exceeded; bar not replayed",
            ))
    await db.commit()
    logger.error("cycle.catchup_truncated_bars_not_replayed", skipped=len(open_times))


async def _ensure_features_persisted(db: AsyncSession, context: MarketContext) -> None:
    exists = (
        await db.execute(
            select(MarketFeatureSet.id).where(
                MarketFeatureSet.symbol == context.symbol,
                MarketFeatureSet.timeframe == context.timeframe,
                MarketFeatureSet.candle_open_time == context.candle_open_time,
            )
        )
    ).first()
    if exists is None:
        db.add(MarketFeatureSet(
            symbol=context.symbol, timeframe=context.timeframe, candle_open_time=context.candle_open_time,
            features=context.model_dump(mode="json"),
        ))
        db.add(MarketRegimeRecord(
            symbol=context.symbol, timeframe=context.timeframe, candle_open_time=context.candle_open_time,
            regime=context.regime.regime, confidence=context.regime.confidence,
            detector_version=context.regime.detector_version,
            detail={"volatility_percentile": context.volatility.volatility_percentile,
                    "volume_ratio": context.volume.volume_ratio},
        ))
        await db.flush()


async def process_candle(
    db: AsyncSession,
    market: MarketDataService,
    ollama_client: OllamaClient,
    open_time: int,
    *,
    is_latest: bool,
    execution_engine=None,
    lease_lost=None,
) -> CycleOutcome | None:
    """Processes ONE confirmed candle. Returns None if it was already completed."""
    from app.core.system_flags import trading_halt_reason  # local: avoid import cycle at module load

    settings = get_settings()
    symbol, timeframe = settings.market_symbol, settings.market_timeframe
    cycle_id = make_cycle_id(symbol, timeframe, open_time)

    cycle = (await db.execute(select(WorkerCycle).where(WorkerCycle.cycle_id == cycle_id))).scalar_one_or_none()
    if cycle is not None:
        if cycle.status in _DONE_STATUSES:
            logger.info("cycle.duplicate_confirmed_candle_skipped", cycle_id=cycle_id)
            return None
        if cycle.attempts >= MAX_CYCLE_ATTEMPTS:
            cycle.status = FAILED_PERMANENT
            await db.commit()
            logger.critical("cycle.poison_candle_abandoned", cycle_id=cycle_id, error=cycle.error)
            return None
        cycle.attempts += 1
        cycle.cycle_started_at = time.time()
        cycle.status = STARTED
    else:
        cycle = WorkerCycle(cycle_id=cycle_id, candle_timestamp=open_time, cycle_started_at=time.time(), status=STARTED)
        db.add(cycle)
    await db.commit()  # the STARTED row is durable, but only COMPLETED counts as done
    started = cycle.cycle_started_at

    try:
        candles = await market.get_recent_candles(db, limit=300, confirmed_only=True, up_to_open_time=open_time)
        if candles.empty or int(candles["open_time"].iloc[-1]) != open_time:
            raise InsufficientDataError(f"confirmed candle {open_time} not present in the store")
        context = compute_features(candles, symbol=symbol, timeframe=timeframe)
        prev_context: MarketContext | None = None
        if len(candles) > MIN_CANDLES_REQUIRED:
            try:
                prev_context = compute_features(candles.iloc[:-1], symbol=symbol, timeframe=timeframe)
            except InsufficientDataError:
                prev_context = None

        await _ensure_features_persisted(db, context)
        await db.commit()

        council_decision_id = None
        council_trade_allowed = True
        council_bias = None
        council_confidence = None
        council_status = "NOT_RUN"
        if (
            is_latest
            and settings.council_enabled
            and council_due(open_time, market.interval_ms, settings.council_interval_candles)
        ):
            try:
                # The council enforces its own per-analyst and whole-council deadlines
                # (cancelling slow calls); this outer guard is only a failsafe.
                consensus = await asyncio.wait_for(
                    run_council_cycle(db, ollama_client, context), timeout=settings.council_deadline_seconds + 15
                )
                council_decision_id = consensus.council_decision_id
                council_trade_allowed = consensus.trade_allowed
                council_status = consensus.council_status
                council_bias, council_confidence = consensus.final_bias, consensus.final_confidence
                logger.info(
                    "cycle.council_decision", final_bias=consensus.final_bias.value,
                    confidence=consensus.final_confidence, council_status=consensus.council_status,
                    quorum_met=consensus.quorum_met, successful_analysts=consensus.successful_analysts,
                    failed_analysts=consensus.failed_analysts, trade_allowed=consensus.trade_allowed,
                    total_council_latency=consensus.total_council_latency,
                )
            except asyncio.TimeoutError:
                await db.rollback()
                # Fail closed: a council that misses its deadline is INCOMPLETE.
                council_trade_allowed = False
                council_status = "INCOMPLETE"
                logger.error("cycle.council_deadline_exceeded", deadline=settings.council_deadline_seconds)

        halt = await trading_halt_reason(db)
        if not is_latest:
            halt = ",".join(filter(None, [halt, "catchup_replay"]))
        if lease_lost is not None and lease_lost():
            raise RuntimeError("worker lease lost before decision phase")

        generation = (
            await db.execute(select(Generation).order_by(Generation.number.desc()).limit(1))
        ).scalar_one_or_none()
        processed = 0
        if generation is not None:
            market_age = await market.latest_candle_age_seconds(db)
            processed = await run_decision_cycle(
                db,
                execution_engine or get_execution_engine(settings),
                context,
                prev_context,
                generation=generation.number,
                council_decision_id=council_decision_id,
                global_max_leverage=settings.max_leverage,
                global_max_position_size=settings.max_position_size,
                global_max_drawdown=settings.max_drawdown,
                global_max_daily_loss=settings.max_daily_loss,
                market_data_age_seconds=market_age if is_latest else None,
                council_trade_allowed=council_trade_allowed,
                council_bias=council_bias,
                council_confidence=council_confidence,
                council_status=council_status if council_status != "NOT_RUN" else None,
                trading_halt_override=halt,
                candles=candles,
            )
            if processed > 0 and await is_population_extinct(db, generation.number):
                await record_extinction(
                    db, generation.number, report={"note": "population extinct", "candle_open_time": open_time},
                )

        cycle.cycle_completed_at = time.time()
        cycle.cycle_latency_seconds = cycle.cycle_completed_at - started
        cycle.completed = True
        cycle.status = COMPLETED
        cycle.agents_processed = processed
        cycle.council_status = council_status
        cycle.trading_halt_reason = halt
        cycle.error = None
        await db.commit()
        return CycleOutcome(
            cycle_id, open_time, COMPLETED, processed, council_status, halt, cycle.cycle_latency_seconds
        )
    except Exception as exc:
        await db.rollback()
        # A fresh statement in a fresh transaction: mark the attempt failed
        # so it is retried (bounded) rather than silently lost.
        cycle_row = (await db.execute(select(WorkerCycle).where(WorkerCycle.cycle_id == cycle_id))).scalar_one()
        cycle_row.status = FAILED
        cycle_row.error = f"{type(exc).__name__}: {exc}"[:2000]
        await db.commit()
        logger.exception("cycle.failed", cycle_id=cycle_id)
        return CycleOutcome(cycle_id, open_time, FAILED)


async def run_pending_cycles(
    db: AsyncSession,
    market: MarketDataService,
    ollama_client: OllamaClient,
    *,
    execution_engine=None,
    lease_lost=None,
    target_open_time: int | None = None,
) -> list[CycleOutcome]:
    """One scheduler tick: sync -> gap check -> replay/process pending bars."""
    await market.sync_recent_candles(db)
    await market.sync_funding_history(db)
    await market.recover_gaps(db)

    if target_open_time is not None:
        await market.wait_for_confirmed_candle(db, target_open_time)

    if await market.is_stale(db):
        logger.error("cycle.market_data_stale_skipping")
        return []

    to_process, to_skip = await pending_open_times(db, market)
    if to_skip:
        await _record_skipped(db, market, to_skip)

    outcomes: list[CycleOutcome] = []
    for idx, open_time in enumerate(to_process):
        outcome = await process_candle(
            db, market, ollama_client, open_time,
            is_latest=(idx == len(to_process) - 1),
            execution_engine=execution_engine,
            lease_lost=lease_lost,
        )
        if outcome is not None:
            outcomes.append(outcome)
            if outcome.status != COMPLETED:
                break  # never process a later bar before an earlier one completed
    return outcomes
