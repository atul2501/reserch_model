"""The main trading worker (spec section 61's end-to-end pipeline).

    Hyperliquid -> MarketDataService -> confirmed candle -> features/regime
        -> AI council (cadence) -> shared context -> all agents (DNA) -> risk
        -> execution -> PnL / equity -> extinction check

Runs as a long-lived process separate from the FastAPI process so a
dashboard restart never interrupts trading. The heavy lifting lives in
`app.worker.cycle` (testable, injectable); this file is the process shell:
lease, candle-boundary scheduling, graceful shutdown.

Usage:
    python -m scripts.run_cycle          # loop forever, one cycle per confirmed candle
    python -m scripts.run_cycle --once   # process pending confirmed candle(s) and exit
"""
from __future__ import annotations

import argparse
import asyncio
import signal

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal, use_immediate_transactions
from app.core.logging import configure_logging, get_logger
from app.execution.router import LiveSafetyGateError, get_execution_engine
from app.market.hyperliquid_client import HyperliquidClient
from app.market.hyperliquid_ws import HyperliquidWebSocket
from app.market.ws_ingest import WsCandleIngestor
from app.market.market_data_service import MarketDataService
from app.services.ollama_client import OllamaClient
from app.core import metrics
from app.core.runtime_status import WORKER, publish_status
from app.worker.cycle import record_cycle_metrics, run_pending_cycles
from app.worker.status import build_worker_payload
from app.worker.key_refresh import KeyRefresher
from app.worker.lease import LeaseKeeper, LeaseLost
from app.worker.scheduler import last_confirmed_open_time, seconds_until_next_confirmation

logger = get_logger(__name__)


class WorkerAlreadyActive(RuntimeError):
    pass


async def main(run_once: bool = False) -> None:
    configure_logging()
    use_immediate_transactions()  # SQLite writer process: queue on the write lock instead of failing (database.py)
    settings = get_settings()
    market_service = MarketDataService()
    ollama_client = OllamaClient()

    try:
        execution_engine = get_execution_engine(settings)  # fail fast if live mode is misconfigured; built ONCE and reused
    except LiveSafetyGateError as exc:
        logger.critical("cycle.live_safety_gate_failed", error=str(exc))
        raise

    interval_ms = HyperliquidClient.timeframe_to_ms(settings.market_timeframe)
    grace_ms = settings.candle_finality_grace_ms

    lease = LeaseKeeper(
        AsyncSessionLocal,
        ttl_seconds=settings.worker_lease_ttl_seconds,
        heartbeat_seconds=settings.worker_lease_heartbeat_seconds,
    )
    if not await lease.acquire():
        logger.critical("worker.already_active_refusing_to_trade")
        await market_service.aclose()
        await ollama_client.aclose()
        raise WorkerAlreadyActive("another decision worker holds the lease")

    ws_task: asyncio.Task | None = None
    ws: HyperliquidWebSocket | None = None
    if settings.market_ws_enabled:
        ws = HyperliquidWebSocket(
            settings.hyperliquid_ws_url, settings.market_symbol, settings.market_timeframe,
            WsCandleIngestor(AsyncSessionLocal, market_service), interval_ms=interval_ms,
            ping_interval=settings.ws_ping_interval_seconds, stale_after=settings.ws_stale_after_seconds,
            future_tolerance_ms=settings.ws_future_tolerance_ms,
        )
        ws_task = asyncio.create_task(ws.run(), name="hyperliquid-ws")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # pragma: no cover (non-POSIX)
            pass
    key_refresher = KeyRefresher(ollama_client, settings.ollama_key_refresh_seconds)
    try:  # `kill -HUP <worker pid>` after rotating a key: reload credentials, re-try every key
        loop.add_signal_handler(signal.SIGHUP, key_refresher.request_forced_refresh)
    except (NotImplementedError, AttributeError, ValueError):  # pragma: no cover (non-POSIX)
        pass

    try:
        while not stop.is_set():
            target = last_confirmed_open_time(HyperliquidClient.now_ms(), interval_ms, grace_ms)
            outcomes = []
            key_refresher.tick()
            try:
                async with AsyncSessionLocal() as db:
                    outcomes = await run_pending_cycles(
                        db, market_service, ollama_client, execution_engine=execution_engine,
                        lease_lost=lambda: lease.is_lost, fence=lease, target_open_time=target,
                    )
                record_cycle_metrics(outcomes)
                for o in outcomes:
                    logger.info(
                        "cycle.done", cycle_id=o.cycle_id, status=o.status, agents=o.agents_processed,
                        council=o.council_status, halt=o.halt_reason, latency=o.latency_seconds,
                    )
            except LeaseLost:
                logger.critical("worker.fenced_off_stopping_all_trading")
            except Exception as exc:
                if isinstance(exc, SQLAlchemyError):
                    metrics.record_db_error("worker_loop")
                logger.exception("cycle.unhandled_error")
            if lease.is_lost:
                logger.critical("worker.lease_lost_exiting")
                break
            try:  # publish runtime state for the API/dashboard (never allowed to break the loop)
                async with AsyncSessionLocal() as db:
                    await publish_status(db, WORKER, build_worker_payload(ollama_client, ws, execution_engine, outcomes))
            except Exception:
                logger.warning("worker.status_publish_failed")
            if lease.is_lost:
                logger.critical("worker.lease_lost_exiting")
                break
            if run_once:
                break
            delay = seconds_until_next_confirmation(HyperliquidClient.now_ms(), interval_ms, grace_ms)
            try:
                await asyncio.wait_for(stop.wait(), timeout=max(0.05, delay))
            except asyncio.TimeoutError:
                pass
    finally:
        if ws is not None and ws_task is not None:
            ws.stop()
            try:
                await asyncio.wait_for(ws_task, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                ws_task.cancel()
        await lease.close()
        await execution_engine.aclose()
        await market_service.aclose()
        await ollama_client.aclose()
        logger.info("worker.stopped")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="process pending confirmed candle(s) and exit")
    args = parser.parse_args()
    asyncio.run(main(run_once=args.once))
