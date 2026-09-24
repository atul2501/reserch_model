"""The research process' event loop must stay responsive (spec phase 16 / audit item: blocking + O(n^2) work).

A heartbeat coroutine stands in for the lease heartbeat and status publishing: if CPU-bound research work runs on the
loop, its ticks stall (and in production the research lease would expire mid-run)."""
from __future__ import annotations

import asyncio
import random
import time

from app.evolution.breeding import select_and_breed_next_generation
from app.evolution.correlation_service import compute_generation_correlation_report
from app.models.enums import StrategyStage
from app.strategies.factory import generate_population_dna
from tests.helpers_agents import make_agents

N = 250
MAX_STALL_SECONDS = 0.35      # generous for CI; a blocked loop stalls for many seconds at this size


class Heartbeat:
    def __init__(self, period=0.01):
        self.period, self.stamps, self._task = period, [], None

    async def _run(self):
        while True:
            self.stamps.append(time.perf_counter())
            await asyncio.sleep(self.period)

    async def __aenter__(self):
        self._task = asyncio.create_task(self._run())
        await asyncio.sleep(0.05)
        return self

    async def __aexit__(self, *a):
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)

    @property
    def max_gap(self) -> float:
        return max((b - a for a, b in zip(self.stamps, self.stamps[1:])), default=0.0)


async def test_correlation_report_does_not_starve_the_event_loop(db_session):
    await make_agents(db_session, generate_population_dna(N, seed=1), generation=1, stage=StrategyStage.PAPER)
    async with Heartbeat() as hb:
        report = await compute_generation_correlation_report(db_session, generation=1)
    assert len(hb.stamps) > 5 and hb.max_gap < MAX_STALL_SECONDS, f"event loop stalled for {hb.max_gap:.2f}s"
    assert report.mean_pairwise_correlation is not None and len(report.agent_mean_correlation) == N


async def test_breeding_does_not_starve_the_event_loop(db_session):
    agents = await make_agents(db_session, generate_population_dna(N, seed=2), generation=1, stage=StrategyStage.PAPER)
    for i, a in enumerate(agents):
        a.equity = a.balance = 100.0 + i
    await db_session.commit()

    def slow_validator(dna):            # a CPU-bound in-sample backtest stand-in
        end = time.perf_counter() + 0.002
        while time.perf_counter() < end:
            pass
        return True, {}

    async with Heartbeat() as hb:
        res = await select_and_breed_next_generation(
            db_session, generation_number=1, survivor_count=100, next_generation_size=N, rng=random.Random(3),
            candidate_validator=slow_validator,
        )
    assert len(res.strategy_version_ids) == N
    assert hb.max_gap < MAX_STALL_SECONDS, f"event loop stalled for {hb.max_gap:.2f}s"


def test_the_pairwise_scans_are_fast_enough_at_production_scale():
    from app.evolution.diversity import dna_signature, most_similar_pair, population_diversity_score

    dnas = generate_population_dna(500, seed=4)
    t0 = time.perf_counter()
    sigs = [dna_signature(d) for d in dnas]
    population_diversity_score(dnas, sigs)
    most_similar_pair(dnas, sigs)
    assert time.perf_counter() - t0 < 6.0        # 125k pairs twice; the naive per-pair spec resolution took far longer


async def test_evaluate_oos_once_runs_off_the_event_loop(db_session):
    from tests.test_frozen_oos_epoch import _sealed
    from tests.test_backtest_parity import ema_cross_dna
    from app.models.strategy import StrategyVersion
    from app.research.lockbox import evaluate_oos_once

    c, epoch = await _sealed(db_session, n=2500)
    (agent,) = await make_agents(db_session, [ema_cross_dna(5, 20)])
    version = await db_session.get(StrategyVersion, agent.strategy_version_id)
    async with Heartbeat() as hb:
        await evaluate_oos_once(db_session, version, epoch, c)
    assert hb.max_gap < MAX_STALL_SECONDS, f"event loop stalled for {hb.max_gap:.2f}s"
