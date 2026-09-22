"""The main trading cycle worker (spec section 61's end-to-end pipeline):

    Hyperliquid -> MarketDataService -> feature engine -> regime detector
        -> AI council (every N candles) -> shared MarketContext
        -> decision loop (all active agents) -> risk engine -> execution
        -> PnL / equity update -> extinction check

Runs as a long-lived background process, separate from the FastAPI process
(see app/main.py docstring) so a dashboard restart never interrupts trading.

Usage:
    python -m scripts.run_cycle          # loop forever, one cycle per candle close
    python -m scripts.run_cycle --once   # run a single cycle and exit (for cron/testing)
"""
from __future__ import annotations

import argparse
import asyncio
import time
import uuid

from sqlalchemy import select

from app.agents.decision_loop import run_decision_cycle
from app.agents.lifecycle import is_population_extinct, record_extinction
from app.core.config import get_settings
from app.core.database import session_scope
from app.core.logging import configure_logging, get_logger
from app.council.service import run_council_cycle, should_run_council
from app.execution.router import LiveSafetyGateError, get_execution_engine
from app.market.feature_engine import InsufficientDataError, compute_features
from app.market.market_data_service import MarketDataService
from app.models.market import MarketFeatureSet, MarketRegimeRecord
from app.models.system import WorkerCycle, WorkerLease
from app.models.enums import Bias
from app.models.strategy import Generation
from app.schemas.market_context import MarketContext
from app.services.ollama_client import OllamaClient

logger = get_logger(__name__)

_prev_context: MarketContext | None = None
_candle_index = 0
_worker_id = str(uuid.uuid4())


async def _acquire_or_refresh_lease(db, *, ttl_seconds: int = 180) -> bool:
    """Best-effort durable single-worker lease. Database decision/cycle
    uniqueness remains the final idempotency barrier if two processes race."""
    now = time.time()
    lease = await db.get(WorkerLease, "decision-worker")
    if lease is not None and lease.owner_id != _worker_id and lease.expires_at > now:
        logger.error("cycle.worker_lease_held", owner_id=lease.owner_id)
        return False
    if lease is None:
        db.add(WorkerLease(name="decision-worker", owner_id=_worker_id, expires_at=now + ttl_seconds))
    else:
        lease.owner_id = _worker_id
        lease.expires_at = now + ttl_seconds
    await db.commit()
    return True


async def run_one_cycle(market_service: MarketDataService, ollama_client: OllamaClient) -> None:
    global _prev_context, _candle_index
    settings = get_settings()

    async with session_scope() as db:
        if not await _acquire_or_refresh_lease(db):
            return
        await market_service.sync_recent_candles(db)

        if await market_service.is_stale(db):
            logger.error("cycle.market_data_stale_skipping")
            return

        candles = await market_service.get_recent_candles(db, limit=300, confirmed_only=True)
        try:
            context = compute_features(candles, symbol=settings.market_symbol, timeframe=settings.market_timeframe)
        except InsufficientDataError as exc:
            logger.warning("cycle.insufficient_data", detail=str(exc))
            return

        cycle_id = f"{context.symbol}:{context.timeframe}:{context.candle_open_time}"
        existing_cycle = await db.execute(
            select(WorkerCycle).where(WorkerCycle.cycle_id == cycle_id)
        )
        if existing_cycle.scalar_one_or_none() is not None:
            logger.info("cycle.duplicate_confirmed_candle_skipped", cycle_id=cycle_id)
            return
        cycle_started = time.time()
        cycle = WorkerCycle(
            cycle_id=cycle_id,
            candle_timestamp=context.candle_open_time,
            cycle_started_at=cycle_started,
        )
        db.add(cycle)
        await db.flush()

        db.add(
            MarketFeatureSet(
                symbol=context.symbol,
                timeframe=context.timeframe,
                candle_open_time=context.candle_open_time,
                features=context.model_dump(mode="json"),
            )
        )
        db.add(
            MarketRegimeRecord(
                symbol=context.symbol,
                timeframe=context.timeframe,
                candle_open_time=context.candle_open_time,
                regime=context.regime.regime,
                confidence=context.regime.confidence,
                detector_version=context.regime.detector_version,
                detail={
                    "volatility_percentile": context.volatility.volatility_percentile,
                    "volume_ratio": context.volume.volume_ratio,
                },
            )
        )
        await db.commit()

        # Both reset fresh every call (local vars, not module globals): a
        # council decision is only ever attached to Decision rows made
        # THIS candle, on THIS call. A candle where the council doesn't run
        # at all (should_run_council is False) gets council_decision_id=None
        # and council_trade_allowed=True (unchanged, pre-existing behavior)
        # rather than silently reusing a previous candle's result — that's
        # what "prevent a stale council result from being used for a later
        # market candle" means here: no cross-candle carry-forward, ever.
        council_decision_id = None
        council_trade_allowed = True
        if settings.council_enabled and should_run_council(_candle_index, settings.council_interval_candles):
            consensus = await run_council_cycle(db, ollama_client, context)
            council_decision_id = consensus.council_decision_id
            council_trade_allowed = consensus.trade_allowed
            logger.info(
                "cycle.council_decision",
                final_bias=consensus.final_bias.value,
                confidence=consensus.final_confidence,
                judge_invoked=consensus.judge_invoked,
                council_status=consensus.council_status,
                quorum_met=consensus.quorum_met,
                expected_analysts=consensus.expected_analysts,
                successful_analysts=consensus.successful_analysts,
                failed_analysts=consensus.failed_analysts,
                failure_reasons=consensus.failure_reasons,
                trade_allowed=consensus.trade_allowed,
                council_start=consensus.council_start,
                consensus_time=consensus.consensus_time,
                total_council_latency=consensus.total_council_latency,
            )
            if not consensus.quorum_met:
                logger.warning(
                    "cycle.council_incomplete_no_new_trades",
                    candle_open_time=context.candle_open_time,
                    successful_analysts=consensus.successful_analysts,
                    required=settings.council_min_successful_analysts,
                )

        latest_generation = (
            await db.execute(select(Generation).order_by(Generation.number.desc()).limit(1))
        ).scalar_one_or_none()

        if latest_generation is not None:
            market_age = await market_service.latest_candle_age_seconds(db)
            processed = await run_decision_cycle(
                db,
                get_execution_engine(settings),
                context,
                _prev_context,
                generation=latest_generation.number,
                council_decision_id=council_decision_id,
                global_max_leverage=settings.max_leverage,
                global_max_position_size=settings.max_position_size,
                global_max_drawdown=settings.max_drawdown,
                global_max_daily_loss=settings.max_daily_loss,
                market_data_age_seconds=market_age,
                council_trade_allowed=council_trade_allowed,
                council_bias=consensus.final_bias if council_decision_id is not None else None,
                council_confidence=consensus.final_confidence if council_decision_id is not None else None,
            )
            logger.info(
                "cycle.agents_processed", count=processed, generation=latest_generation.number,
                council_trade_allowed=council_trade_allowed,
            )

            if processed > 0 and await is_population_extinct(db, latest_generation.number):
                # Spec section 15/52: record extinction; a human/researcher
                # (or a separate scheduled job) must run the bootstrap script
                # to spin up the next generation after reviewing the report —
                # this loop does NOT auto-recreate a population silently.
                await record_extinction(
                    db,
                    latest_generation.number,
                    report={"note": "TODO: populate full extinction report (spec section 52)"},
                )

        cycle.cycle_completed_at = time.time()
        cycle.cycle_latency_seconds = cycle.cycle_completed_at - cycle_started
        cycle.completed = True
        await db.commit()

        _prev_context = context
        _candle_index += 1


async def main(run_once: bool = False) -> None:
    configure_logging()
    settings = get_settings()
    market_service = MarketDataService()
    ollama_client = OllamaClient()

    try:
        get_execution_engine(settings)  # fail fast if live mode is misconfigured
    except LiveSafetyGateError as exc:
        logger.critical("cycle.live_safety_gate_failed", error=str(exc))
        raise

    interval_seconds = 60 if settings.market_timeframe == "1m" else 300

    try:
        while True:
            try:
                await run_one_cycle(market_service, ollama_client)
            except Exception:
                logger.exception("cycle.unhandled_error")
            if run_once:
                break
            # Align wake-up to the next exchange candle boundary rather than
            # adding an interval after variable council/DB work completes.
            now = time.time()
            await asyncio.sleep(max(0.25, interval_seconds - (now % interval_seconds) + 0.25))
    finally:
        await market_service.aclose()
        await ollama_client.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="run a single cycle and exit")
    args = parser.parse_args()
    asyncio.run(main(run_once=args.once))
