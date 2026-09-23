"""Worker cycle integrity (spec phases 1, 2, 21): confirmed candles only,
idempotency, crash safety, catch-up replay, halts."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.agents.lifecycle import create_generation
from app.execution.paper_adapter import PaperExecutionAdapter
from app.market.market_data_service import MarketDataService
from app.core.system_flags import KILL_SWITCH, set_flag
from app.models.decision import Decision
from app.models.enums import StrategyFamily
from app.models.strategy import Strategy, StrategyVersion
from app.models.system import WorkerCycle
from app.schemas.strategy_dna import Condition, RiskProfile, RuleSet, StrategyDNA
from app.worker import cycle as cycle_mod
from tests.helpers_market import INTERVAL, T0, FakeHyperliquid, clock_after_bar


async def _seed_population(db, n=3):
    ids = []
    for _ in range(n):
        strat = Strategy(code=f"S-{uuid.uuid4().hex[:8]}", family=StrategyFamily.MOMENTUM, name="t")
        db.add(strat)
        await db.flush()
        dna = StrategyDNA(
            strategy_family=StrategyFamily.MOMENTUM,
            indicators=[{"name": "rsi", "params": {"period": 14}}],
            entry_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="gt", value=60)]),
            exit_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="lt", value=40)]),
            risk_profile=RiskProfile(max_leverage=1.0, max_position_fraction=0.5),
        )
        v = StrategyVersion(strategy_id=strat.id, version=1, generation=1, dna=dna.model_dump(mode="json"))
        db.add(v)
        await db.flush()
        ids.append(v.id)
    await create_generation(db, generation_number=1, strategy_version_ids=ids, starting_balance=100.0)


@pytest.fixture
def no_council(monkeypatch):
    from app.core.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "council_enabled", False)
    monkeypatch.setattr(s, "paper_latency_ms", 0)
    return s


async def _setup(db, *, last_bar=399, n_bars=400):
    fake = FakeHyperliquid(n_candles=n_bars)
    market = MarketDataService(fake, clock_ms=lambda: clock_after_bar(last_bar))
    await _seed_population(db)
    await market.sync_recent_candles(db, lookback_candles=n_bars)
    return fake, market


async def _cycles(db):
    return {c.candle_timestamp: c for c in (await db.execute(select(WorkerCycle))).scalars().all()}


async def test_latest_confirmed_bar_processed_and_recorded(db_session, no_council):
    _, market = await _setup(db_session)
    outcomes = await cycle_mod.run_pending_cycles(db_session, market, None, execution_engine=PaperExecutionAdapter())
    assert [o.status for o in outcomes] == ["COMPLETED"]  # cold start: latest bar only, history not replayed
    assert outcomes[0].candle_open_time == T0 + 399 * INTERVAL
    row = (await _cycles(db_session))[T0 + 399 * INTERVAL]
    assert row.status == "COMPLETED" and row.completed and row.agents_processed == 3
    assert row.cycle_latency_seconds is not None and row.council_status == "NOT_RUN"
    decisions = (await db_session.execute(select(Decision))).scalars().all()
    assert len(decisions) == 3 and {d.market_candle_open_time for d in decisions} == {T0 + 399 * INTERVAL}


async def test_open_bar_is_never_processed(db_session, no_council):
    fake = FakeHyperliquid(n_candles=400)
    now = T0 + 399 * INTERVAL + 20_000  # bar 399 still open
    market = MarketDataService(fake, clock_ms=lambda: now)
    await _seed_population(db_session)
    await market.sync_recent_candles(db_session, lookback_candles=400)
    outcomes = await cycle_mod.run_pending_cycles(db_session, market, None, execution_engine=PaperExecutionAdapter())
    assert [o.candle_open_time for o in outcomes] == [T0 + 398 * INTERVAL]
    assert T0 + 399 * INTERVAL not in await _cycles(db_session)


async def test_completed_candle_is_never_reprocessed(db_session, no_council):
    _, market = await _setup(db_session)
    eng = PaperExecutionAdapter()
    await cycle_mod.run_pending_cycles(db_session, market, None, execution_engine=eng)
    again = await cycle_mod.run_pending_cycles(db_session, market, None, execution_engine=eng)
    assert again == []
    n = len((await db_session.execute(select(Decision))).scalars().all())
    assert n == 3


async def test_crash_mid_cycle_leaves_candle_pending_and_retry_succeeds(db_session, no_council, monkeypatch):
    _, market = await _setup(db_session)
    real = cycle_mod.run_decision_cycle
    state = {"n": 0}

    async def flaky(*a, **kw):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("boom mid-cycle")
        return await real(*a, **kw)

    monkeypatch.setattr(cycle_mod, "run_decision_cycle", flaky)
    eng = PaperExecutionAdapter()
    first = await cycle_mod.run_pending_cycles(db_session, market, None, execution_engine=eng)
    assert first[0].status == "FAILED"
    row = (await _cycles(db_session))[T0 + 399 * INTERVAL]
    assert row.status == "FAILED" and "boom" in row.error and row.attempts == 1

    second = await cycle_mod.run_pending_cycles(db_session, market, None, execution_engine=eng)
    assert second[0].status == "COMPLETED"
    row = (await _cycles(db_session))[T0 + 399 * INTERVAL]
    assert row.status == "COMPLETED" and row.attempts == 2 and row.error is None


async def test_poison_candle_is_abandoned_after_max_attempts(db_session, no_council, monkeypatch):
    _, market = await _setup(db_session)

    async def always_fail(*a, **kw):
        raise RuntimeError("poison")

    monkeypatch.setattr(cycle_mod, "run_decision_cycle", always_fail)
    eng = PaperExecutionAdapter()
    for _ in range(cycle_mod.MAX_CYCLE_ATTEMPTS + 1):
        await cycle_mod.run_pending_cycles(db_session, market, None, execution_engine=eng)
    row = (await _cycles(db_session))[T0 + 399 * INTERVAL]
    assert row.status == "FAILED_PERMANENT"


async def test_overrun_bars_are_replayed_in_order_with_entries_disabled_except_latest(db_session, no_council, monkeypatch):
    _, market = await _setup(db_session)
    # Pretend bar 396 was the last completed cycle; 397, 398, 399 are pending.
    db_session.add(WorkerCycle(cycle_id=f"SOL:1m:{T0 + 396 * INTERVAL}", candle_timestamp=T0 + 396 * INTERVAL,
                               cycle_started_at=1.0, completed=True, status="COMPLETED"))
    await db_session.commit()

    seen = []
    real = cycle_mod.run_decision_cycle

    async def spy(db, eng, context, prev, **kw):
        seen.append((context.candle_open_time, kw.get("trading_halt_override")))
        return await real(db, eng, context, prev, **kw)

    monkeypatch.setattr(cycle_mod, "run_decision_cycle", spy)
    outcomes = await cycle_mod.run_pending_cycles(db_session, market, None, execution_engine=PaperExecutionAdapter())
    assert [o.candle_open_time for o in outcomes] == [T0 + i * INTERVAL for i in (397, 398, 399)]
    assert [t for t, _ in seen] == [T0 + i * INTERVAL for i in (397, 398, 399)]
    assert "catchup_replay" in seen[0][1] and "catchup_replay" in seen[1][1]
    assert not seen[2][1]  # only the newest bar may open positions


async def test_catchup_window_is_bounded_and_skipped_bars_are_audited(db_session, no_council, monkeypatch):
    _, market = await _setup(db_session)
    monkeypatch.setattr(no_council, "max_catchup_bars", 2)
    db_session.add(WorkerCycle(cycle_id=f"SOL:1m:{T0 + 390 * INTERVAL}", candle_timestamp=T0 + 390 * INTERVAL,
                               cycle_started_at=1.0, completed=True, status="COMPLETED"))
    await db_session.commit()
    outcomes = await cycle_mod.run_pending_cycles(db_session, market, None, execution_engine=PaperExecutionAdapter())
    assert [o.candle_open_time for o in outcomes] == [T0 + 398 * INTERVAL, T0 + 399 * INTERVAL]
    cycles = await _cycles(db_session)
    skipped = [t for t, c in cycles.items() if c.status == "SKIPPED_CATCHUP"]
    assert sorted(skipped) == [T0 + i * INTERVAL for i in range(391, 398)]


async def test_kill_switch_reaches_the_decision_loop(db_session, no_council, monkeypatch):
    _, market = await _setup(db_session)
    await set_flag(db_session, KILL_SWITCH, True, reason="drill")
    await db_session.commit()
    captured = {}
    real = cycle_mod.run_decision_cycle

    async def spy(db, eng, ctx, prev, **kw):
        captured.update(kw)
        return await real(db, eng, ctx, prev, **kw)

    monkeypatch.setattr(cycle_mod, "run_decision_cycle", spy)
    outcomes = await cycle_mod.run_pending_cycles(db_session, market, None, execution_engine=PaperExecutionAdapter())
    assert outcomes[0].halt_reason == KILL_SWITCH
    assert captured["trading_halt_override"] == KILL_SWITCH


async def test_lease_lost_before_decisions_aborts_without_writing_decisions(db_session, no_council):
    _, market = await _setup(db_session)
    outcomes = await cycle_mod.run_pending_cycles(
        db_session, market, None, execution_engine=PaperExecutionAdapter(), lease_lost=lambda: True
    )
    assert outcomes[0].status == "FAILED"
    assert (await db_session.execute(select(Decision))).scalars().all() == []
