"""Scheduled research / evolution worker (spec phase 22).

    python -m scripts.run_research            # loop: check gates every RESEARCH_POLL_SECONDS
    python -m scripts.run_research --once     # evaluate the gates once (run if due) and exit
    python -m scripts.run_research --force    # run one cycle now, ignoring interval/age/paper-history gates

Holds its own durable lease ("research-worker") so two research processes can
never evolve the same population, and never competes with the trading worker
(its own process). All gates and skip reasons are recorded as Experiments.
"""
from __future__ import annotations

import argparse
import asyncio
import signal

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.core.logging import configure_logging, get_logger
from app.market.market_data_service import MarketDataService
from app.research.pipeline import run_research_cycle
from app.worker.lease import LeaseKeeper

logger = get_logger(__name__)
RESEARCH_LEASE = "research-worker"


async def main(*, once: bool, force: bool) -> None:
    configure_logging()
    settings = get_settings()
    lease = LeaseKeeper(
        AsyncSessionLocal, name=RESEARCH_LEASE, ttl_seconds=max(300, settings.worker_lease_ttl_seconds),
        heartbeat_seconds=settings.worker_lease_heartbeat_seconds,
    )
    if not await lease.acquire():
        logger.critical("research.already_active_refusing_to_run")
        raise SystemExit(2)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # pragma: no cover
            pass

    market = MarketDataService()
    try:
        while not stop.is_set():
            try:
                async with AsyncSessionLocal() as db:
                    report = await run_research_cycle(db, market_service=market, force=force)
                logger.info("research.cycle", status=report.status, reason=report.reason, counts=report.counts,
                            experiment_id=report.experiment_id, generation_from=report.generation_from,
                            generation_to=report.generation_to)
            except Exception:
                logger.exception("research.unhandled_error")
            if once or force or lease.is_lost:
                break
            try:
                await asyncio.wait_for(stop.wait(), timeout=settings.research_poll_seconds)
            except asyncio.TimeoutError:
                pass
    finally:
        await lease.close()
        await market.aclose()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    asyncio.run(main(once=a.once, force=a.force))
