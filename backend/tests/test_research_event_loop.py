"""The research process' event loop must stay responsive (spec phase 16 / audit item: blocking + O(n^2) work).

What is being proven: the CPU-bound research work (correlation report build, breeding/validation, OOS backtest) runs
OFF the event-loop thread, so lease heartbeats and status publishing keep running while it computes.

The correctness tests prove that DIRECTLY and DETERMINISTICALLY with `OffLoopProbe` (no wall-clock thresholds, so
they cannot flake on a busy machine): the CPU-bound callee blocks its own thread until a coroutine that can only run
on the event loop acknowledges it. If the callee ran on the loop thread, the loop could not run that coroutine and
the handshake would time out - a guaranteed failure, independent of machine speed.

The original wall-clock heartbeat checks are kept, unchanged in strictness, as opt-in PERFORMANCE tests
(`pytest -m performance`): they measure how responsive the loop is on the current machine, which is a benchmark, not
a correctness property.
"""
from __future__ import annotations

import asyncio
import random
import threading
import time

import pytest

from app.evolution.breeding import select_and_breed_next_generation
from app.evolution.correlation_service import compute_generation_correlation_report
from app.models.enums import StrategyStage
from app.strategies.factory import generate_population_dna
from tests.helpers_agents import make_agents

N = 250
MAX_STALL_SECONDS = 0.35      # performance-test threshold (unchanged); a blocked loop stalls for many seconds at this size
HANDSHAKE_TIMEOUT_S = 10.0


class OffLoopProbe:
    """Wraps a CPU-bound callable. On its first call it records the executing thread, then blocks that thread until
    `watcher()` - a coroutine on the event loop - acknowledges. Running the callee on the loop thread makes the
    acknowledgement impossible, so `blocked_loop` becomes True after the timeout."""

    def __init__(self) -> None:
        self.loop_thread = threading.get_ident()
        self.work_thread: int | None = None
        self.blocked_loop: bool | None = None
        self._started, self._ack = threading.Event(), threading.Event()

    def wrap(self, fn):
        def probed(*a, **k):
            if self.work_thread is None:
                self.work_thread = threading.get_ident()
                self._started.set()
                self.blocked_loop = not self._ack.wait(HANDSHAKE_TIMEOUT_S)
            return fn(*a, **k)
        return probed

    async def watcher(self) -> None:
        while not self._started.is_set():
            await asyncio.sleep(0.001)
        self._ack.set()

    async def __aenter__(self):
        self._task = asyncio.create_task(self.watcher())
        return self

    async def __aexit__(self, *exc):
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)

    def assert_ran_off_loop(self) -> None:
        assert self.work_thread is not None, "the CPU-bound callee was never invoked"
        assert self.work_thread != self.loop_thread, "CPU-bound work ran ON the event-loop thread"
        assert self.blocked_loop is False, "the event loop could not run while the CPU-bound work was in progress"


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


def test_probe_detects_work_on_the_loop_thread():
    """The probe itself must FAIL when work is not offloaded (otherwise the tests below would prove nothing)."""
    async def scenario():
        probe = OffLoopProbe()
        global HANDSHAKE_TIMEOUT_S
        saved, HANDSHAKE_TIMEOUT_S = HANDSHAKE_TIMEOUT_S, 0.2
        try:
            async with probe:
                probe.wrap(lambda: None)()                 # called directly on the loop thread
        finally:
            HANDSHAKE_TIMEOUT_S = saved
        return probe
    probe = asyncio.run(scenario())
    assert probe.work_thread == probe.loop_thread and probe.blocked_loop is True
    with pytest.raises(AssertionError):
        probe.assert_ran_off_loop()


# --------------------------------------------------------------------------- deterministic correctness tests
async def test_correlation_report_runs_off_the_event_loop(db_session, monkeypatch):
    from app.evolution import correlation_service as cs

    await make_agents(db_session, generate_population_dna(N, seed=1), generation=1, stage=StrategyStage.PAPER)
    probe = OffLoopProbe()
    monkeypatch.setattr(cs, "_build_report", probe.wrap(cs._build_report))
    async with probe:
        report = await compute_generation_correlation_report(db_session, generation=1)
    probe.assert_ran_off_loop()
    assert report.mean_pairwise_correlation is not None and len(report.agent_mean_correlation) == N


async def test_breeding_runs_off_the_event_loop(db_session):
    agents = await make_agents(db_session, generate_population_dna(N, seed=2), generation=1, stage=StrategyStage.PAPER)
    for i, a in enumerate(agents):
        a.equity = a.balance = 100.0 + i
    await db_session.commit()
    probe = OffLoopProbe()
    async with probe:
        res = await select_and_breed_next_generation(
            db_session, generation_number=1, survivor_count=100, next_generation_size=N, rng=random.Random(3),
            candidate_validator=probe.wrap(lambda dna: (True, {})),
        )
    probe.assert_ran_off_loop()
    assert len(res.strategy_version_ids) == N


async def test_evaluate_oos_once_runs_off_the_event_loop(db_session, monkeypatch):
    from app.models.strategy import StrategyVersion
    from app.research import lockbox
    from tests.test_backtest_parity import ema_cross_dna
    from tests.test_frozen_oos_epoch import _sealed

    c, epoch = await _sealed(db_session, n=2500)
    (agent,) = await make_agents(db_session, [ema_cross_dna(5, 20)])
    version = await db_session.get(StrategyVersion, agent.strategy_version_id)
    probe = OffLoopProbe()
    monkeypatch.setattr(lockbox, "run_backtest", probe.wrap(lockbox.run_backtest))
    async with probe:
        await lockbox.evaluate_oos_once(db_session, version, epoch, c)
    probe.assert_ran_off_loop()


# --------------------------------------------------------------------------- performance (opt-in: -m performance)
@pytest.mark.performance
async def test_correlation_report_does_not_starve_the_event_loop(db_session):
    await make_agents(db_session, generate_population_dna(N, seed=1), generation=1, stage=StrategyStage.PAPER)
    async with Heartbeat() as hb:
        report = await compute_generation_correlation_report(db_session, generation=1)
    assert len(hb.stamps) > 5 and hb.max_gap < MAX_STALL_SECONDS, f"event loop stalled for {hb.max_gap:.2f}s"
    assert report.mean_pairwise_correlation is not None and len(report.agent_mean_correlation) == N


@pytest.mark.performance
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


@pytest.mark.performance
def test_the_pairwise_scans_are_fast_enough_at_production_scale():
    from app.evolution.diversity import dna_signature, most_similar_pair, population_diversity_score

    dnas = generate_population_dna(500, seed=4)
    t0 = time.perf_counter()
    sigs = [dna_signature(d) for d in dnas]
    population_diversity_score(dnas, sigs)
    most_similar_pair(dnas, sigs)
    assert time.perf_counter() - t0 < 6.0        # 125k pairs twice; the naive per-pair spec resolution took far longer


@pytest.mark.performance
async def test_evaluate_oos_once_does_not_starve_the_event_loop(db_session):
    from tests.test_frozen_oos_epoch import _sealed
    from tests.test_backtest_parity import ema_cross_dna
    from app.models.strategy import StrategyVersion
    from app.research.lockbox import evaluate_oos_once
    from app.research.registry import warm_provenance_cache

    c, epoch = await _sealed(db_session, n=2500)
    (agent,) = await make_agents(db_session, [ema_cross_dna(5, 20)])
    version = await db_session.get(StrategyVersion, agent.strategy_version_id)
    warm_provenance_cache()            # exactly what scripts/run_research.py does at process start-up
    async with Heartbeat() as hb:
        await evaluate_oos_once(db_session, version, epoch, c)
    assert hb.max_gap < MAX_STALL_SECONDS, f"event loop stalled for {hb.max_gap:.2f}s"
