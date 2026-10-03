"""PRETRADE_MODE=shadow integration + paper-fill timing.

Covers the 10 required properties:
  1/2  no fill at a price printed before the decision; fill timestamp >= decision timestamp
  3    no future candle is used to construct a shadow decision
  4-6  shadow mode creates no order, no position, and changes no balance/agent/risk state (incl. DB-enforced read-only)
  7    PRETRADE_MODE=off preserves existing behaviour (identical results to shadow's existing path; shadow never runs)
  8    council latency cannot block the deterministic path
  9    stale decisions are rejected
  10   price-drift rejection works in both directions
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.agents.lifecycle import create_generation
from app.core.config import Settings, get_settings
from app.core.database import Base
from app.execution.paper_adapter import PaperExecutionAdapter
from app.execution.price_observation import PriceObservation, bar_observations, first_observed_at_or_after
from app.market.feature_engine import FEATURE_WINDOW, compute_features
from app.market.market_data_service import MarketDataService
from app.models.agent import Agent
from app.models.decision import Decision
from app.models.enums import Bias, OrderStatus, StrategyFamily
from app.models.strategy import Strategy, StrategyVersion
from app.models.trading import Order, Position, Trade
from app.pretrade.council_view import CouncilSnapshot, CouncilView
from app.pretrade.shadow import LookAheadError, ShadowRecorder, read_only_session, run_shadow_cycle
from app.schemas.strategy_dna import Condition, RiskProfile, RuleSet, StrategyDNA
from app.worker import cycle as cycle_mod
from tests.helpers_market import INTERVAL, T0, FakeHyperliquid, clock_after_bar

LAST = 399


# --------------------------------------------------------------------------- fixtures
def _always(mode: str) -> StrategyDNA:
    """A DNA whose entry rule is always true (close > 0): a deterministic LONG or SHORT candidate on every bar."""
    return StrategyDNA(
        strategy_family=StrategyFamily.MOMENTUM, direction_mode=mode,
        indicators=[{"name": "rsi", "params": {"period": 14}}],
        entry_rules=RuleSet(conditions=[Condition(feature="close", operator="gt", value=0)]),
        exit_rules=RuleSet(conditions=[Condition(feature="close", operator="lt", value=0)]),
        risk_profile=RiskProfile(max_leverage=1.0, max_position_fraction=0.5),
    )


async def _seed(db, modes=("long_only", "short_only", "long_only")):
    ids = []
    for m in modes:
        st = Strategy(code=f"S-{uuid.uuid4().hex[:8]}", family=StrategyFamily.MOMENTUM, name="t")
        db.add(st)
        await db.flush()
        v = StrategyVersion(strategy_id=st.id, version=1, generation=1, dna=_always(m).model_dump(mode="json"))
        db.add(v)
        await db.flush()
        ids.append(v.id)
    await create_generation(db, generation_number=1, strategy_version_ids=ids, starting_balance=100.0)


class FakeBook:
    """Public l2Book stand-in: best bid/ask around `mid` (or failing)."""

    def __init__(self, mid: float | None = None, half_spread: float = 0.005, fail: bool = False):
        self.mid, self.half, self.fail, self.calls = mid, half_spread, fail, 0

    async def get_l2_book(self, coin):
        self.calls += 1
        if self.fail:
            raise RuntimeError("book down")
        return {"coin": coin, "time": 0, "levels": [[{"px": str(self.mid - self.half), "sz": "10", "n": 1}],
                                                    [{"px": str(self.mid + self.half), "sz": "10", "n": 1}]]}


@pytest.fixture
def shadow_on(monkeypatch, tmp_path):
    s = get_settings()
    monkeypatch.setattr(s, "council_enabled", False)
    monkeypatch.setattr(s, "paper_latency_ms", 0)
    monkeypatch.setattr(s, "pretrade_mode", "shadow")
    monkeypatch.setattr(s, "pretrade_shadow_dir", str(tmp_path / "shadow"))
    state = {"view": CouncilView(), "recorder": ShadowRecorder(tmp_path / "shadow"), "book": FakeBook(mid=None, fail=True)}
    monkeypatch.setattr(cycle_mod, "_pretrade_state", state)
    return s, state


def _records(state, kind="candidate"):
    d = state["recorder"].directory
    rows = []
    for p in sorted(d.glob("*.jsonl")) if d.exists() else []:
        rows += [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r for r in rows if r.get("record_type") == kind]


async def _market(db, n=LAST + 1):
    fake = FakeHyperliquid(n_candles=n)
    market = MarketDataService(fake, clock_ms=lambda: clock_after_bar(n - 1))
    await market.sync_recent_candles(db, lookback_candles=n)
    return fake, market


async def _state(db):
    """Production-relevant state, keyed by deterministic agent identifiers (not random ids)."""
    ident = {a.id: a.identifier for a in (await db.execute(select(Agent))).scalars().all()}
    agents = sorted((a.identifier, a.status.value, round(a.balance, 12), round(a.equity, 12), a.trade_count,
                     a.daily_trade_count, a.cooldown_until) for a in (await db.execute(select(Agent))).scalars().all())
    orders = sorted((ident[o.agent_id], o.side.value, o.status.value, o.requested_price, round(o.quantity or 0, 12))
                    for o in (await db.execute(select(Order))).scalars().all())
    positions = sorted((ident[p.agent_id], p.side.value, p.is_open, p.entry_price, round(p.quantity, 12))
                       for p in (await db.execute(select(Position))).scalars().all())
    decisions = sorted((ident[d.agent_id], d.market_candle_open_time, d.agent_signal.value, d.risk_decision.value)
                       for d in (await db.execute(select(Decision))).scalars().all())
    trades = len((await db.execute(select(Trade))).scalars().all())
    return dict(agents=agents, orders=orders, positions=positions, decisions=decisions, trades=trades)


async def _fresh_schema(db_engine):
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


# --------------------------------------------------------------------------- configuration safety
def test_pretrade_mode_defaults_off_and_on_is_refused(monkeypatch):
    assert Settings.model_fields["pretrade_mode"].default == "off"
    assert Settings.model_fields["paper_entry_price_source"].default == "next_open"
    monkeypatch.setenv("PRETRADE_MODE", "on")
    with pytest.raises(Exception, match="separate review"):
        Settings()
    monkeypatch.setenv("PRETRADE_MODE", "shadow")
    assert Settings().pretrade_mode == "shadow"


# --------------------------------------------------------------------------- 4/5/6: shadow writes nothing
async def test_shadow_mode_creates_no_order_position_or_state_change(db_session, shadow_on):
    _, state = shadow_on
    await _seed(db_session)
    _, market = await _market(db_session)
    candles = await market.get_recent_candles(db_session, limit=FEATURE_WINDOW, confirmed_only=True,
                                              up_to_open_time=T0 + LAST * INTERVAL)
    ctx = compute_features(candles, symbol="SOL", timeframe="1m").model_copy(update={"is_final": True})
    before = await _state(db_session)
    state["book"] = FakeBook(mid=ctx.close_price)
    summary = await run_shadow_cycle(bind=db_session.bind, context=ctx, prev_context=None, candles=candles,
                                     generation=None, settings=get_settings(), council_view=state["view"],
                                     recorder=state["recorder"], book_provider=state["book"])
    db_session.expire_all()
    after = await _state(db_session)
    assert summary["candidates"] == 3 and len(_records(state)) == 3
    assert before == after                                         # no order, position, decision, balance, agent change
    assert after["orders"] == [] and after["positions"] == []
    assert all(r["orders_created"] == 0 for r in _records(state))


async def test_shadow_transaction_is_read_only_at_the_database_level(db_session):
    await _seed(db_session)
    async with read_only_session(db_session.bind) as s:
        agent = (await s.execute(select(Agent))).scalars().first()
        agent.balance = 1_000_000.0
        with pytest.raises(OperationalError):
            await s.flush()                                        # the DATABASE refuses the write
        await s.rollback()
    db_session.expire_all()
    assert all(a.balance == 100.0 for a in (await db_session.execute(select(Agent))).scalars().all())
    a = (await db_session.execute(select(Agent))).scalars().first()  # pooled connection is writable again afterwards
    a.trade_count = 7
    await db_session.commit()


# --------------------------------------------------------------------------- 7: OFF preserves behaviour
async def test_off_mode_never_runs_shadow(db_session, monkeypatch, tmp_path):
    s = get_settings()
    monkeypatch.setattr(s, "council_enabled", False)
    monkeypatch.setattr(s, "pretrade_mode", "off")
    monkeypatch.setattr(s, "pretrade_shadow_dir", str(tmp_path / "shadow"))
    monkeypatch.setattr(cycle_mod, "_pretrade_state", {})
    calls = []

    async def _boom(*a, **k):
        calls.append(a)
        raise AssertionError("shadow must not run in OFF mode")
    monkeypatch.setattr(cycle_mod, "_pretrade_shadow_step", _boom)
    monkeypatch.setattr(cycle_mod, "_pretrade_old_path_point", _boom)
    await _seed(db_session)
    _, market = await _market(db_session)
    out = await cycle_mod.run_pending_cycles(db_session, market, None, execution_engine=PaperExecutionAdapter())
    assert [o.status for o in out] == ["COMPLETED"]
    assert calls == [] and cycle_mod._pretrade_state == {}           # never called, nothing initialised
    assert not (tmp_path / "shadow").exists()                        # no shadow output in OFF mode


async def test_shadow_mode_leaves_the_existing_path_identical_to_off(db_engine, db_session, monkeypatch, tmp_path, shadow_on):
    async def run(mode):
        await _fresh_schema(db_engine)
        monkeypatch.setattr(get_settings(), "pretrade_mode", mode)
        from sqlalchemy.ext.asyncio import async_sessionmaker
        async with async_sessionmaker(bind=db_engine, expire_on_commit=False)() as db:
            await _seed(db)
            fake = FakeHyperliquid(n_candles=LAST + 2)
            fake.hidden = {T0 + (LAST + 1) * INTERVAL}
            m1 = MarketDataService(fake, clock_ms=lambda: clock_after_bar(LAST))
            await cycle_mod.run_pending_cycles(db, m1, None, execution_engine=PaperExecutionAdapter())   # decide on bar LAST
            fake.hidden = set()
            m2 = MarketDataService(fake, clock_ms=lambda: clock_after_bar(LAST + 1))
            await cycle_mod.run_pending_cycles(db, m2, None, execution_engine=PaperExecutionAdapter())   # fill on LAST+1
            return await _state(db)

    _, state = shadow_on
    state["book"] = FakeBook(mid=100.0)
    off = await run("off")
    shadow = await run("shadow")
    assert off == shadow
    assert off["orders"] and off["positions"]                      # the existing path really traded in both runs
    assert len(_records(state)) > 0                                # and shadow really ran in the second
    assert len(_records(state, "old_path_point")) > 0


# --------------------------------------------------------------------------- 8: council cannot block
async def test_council_latency_cannot_block_the_deterministic_path(db_session, monkeypatch, shadow_on):
    s, state = shadow_on
    monkeypatch.setattr(s, "council_enabled", True)
    monkeypatch.setattr(cycle_mod, "council_due", lambda *a, **k: True)
    seen = {}

    async def slow_council(db, client, context):
        seen["shadow_rows_when_council_started"] = len(_records(state))
        await asyncio.sleep(0.3)                                   # an LLM that is still thinking
        seen["council_done"] = True
        return SimpleNamespace(candle_open_time=context.candle_open_time, council_decision_id=None, trade_allowed=True,
                               council_status="COMPLETE", final_bias=Bias.SHORT, final_confidence=0.9, quorum_met=True,
                               successful_analysts=8, failed_analysts=[], total_council_latency=0.3)
    monkeypatch.setattr(cycle_mod, "run_council_cycle", slow_council)
    await _seed(db_session)
    _, market = await _market(db_session)
    await cycle_mod.run_pending_cycles(db_session, market, None, execution_engine=PaperExecutionAdapter())
    assert seen["shadow_rows_when_council_started"] == 3           # all shadow decisions existed BEFORE the LLM started
    rows = _records(state)
    assert all(r["council_available"] is False for r in rows)      # the in-flight council was not waited for
    assert all(r["decision_ms"] >= r["information_cutoff_ms"] for r in rows)
    snap = state["view"].latest_any()                              # ...but its result is captured for the NEXT bar
    assert snap is not None and snap.bias == "SHORT" and snap.information_cutoff_ms == T0 + LAST * INTERVAL + INTERVAL - 1


async def test_llm_is_recorded_but_never_authorises_or_vetoes(db_session, shadow_on):
    _, state = shadow_on
    await _seed(db_session)
    _, market = await _market(db_session)
    candles = await market.get_recent_candles(db_session, limit=FEATURE_WINDOW, confirmed_only=True,
                                              up_to_open_time=T0 + LAST * INTERVAL)
    ctx = compute_features(candles, symbol="SOL", timeframe="1m").model_copy(update={"is_final": True})
    cutoff = ctx.candle_open_time + INTERVAL - 1
    state["view"].publish(CouncilSnapshot("SHORT", 0.99, cutoff - INTERVAL, cutoff, "m", None, "COMPLETE"))
    state["book"] = FakeBook(mid=ctx.close_price)
    await run_shadow_cycle(bind=db_session.bind, context=ctx, prev_context=None, candles=candles, generation=None,
                           settings=get_settings(), council_view=state["view"], recorder=state["recorder"],
                           book_provider=state["book"], clock=lambda: cutoff + 1_000)
    rows = _records(state)
    longs = [r for r in rows if r["direction"] == "LONG"]
    assert longs and all(r["llm_would_veto"] and r["llm_agrees"] is False for r in longs)
    assert all(r["gate_allowed"] for r in rows)                    # a 0.99-confidence opposed LLM changes nothing
    assert all(r["council_age_ms"] == 1_000 + INTERVAL for r in rows)


# --------------------------------------------------------------------------- 3/9/10: look-ahead, staleness, drift
async def _ctx(db):
    await _seed(db)
    _, market = await _market(db, n=LAST + 3)
    candles = await market.get_recent_candles(db, limit=FEATURE_WINDOW, confirmed_only=True, up_to_open_time=T0 + LAST * INTERVAL)
    ctx = compute_features(candles, symbol="SOL", timeframe="1m").model_copy(update={"is_final": True})
    return market, candles, ctx


async def test_no_future_candle_can_enter_a_shadow_decision(db_session, shadow_on):
    _, state = shadow_on
    market, candles, ctx = await _ctx(db_session)
    future = await market.get_recent_candles(db_session, limit=FEATURE_WINDOW, confirmed_only=True,
                                             up_to_open_time=T0 + (LAST + 2) * INTERVAL)
    with pytest.raises(LookAheadError):
        await run_shadow_cycle(bind=db_session.bind, context=ctx, prev_context=None, candles=future, generation=None,
                               settings=get_settings(), council_view=state["view"], recorder=state["recorder"])
    with pytest.raises(LookAheadError):
        await run_shadow_cycle(bind=db_session.bind, context=ctx.model_copy(update={"is_final": False}), prev_context=None,
                               candles=candles, generation=None, settings=get_settings(), council_view=state["view"],
                               recorder=state["recorder"])
    await run_shadow_cycle(bind=db_session.bind, context=ctx, prev_context=None, candles=candles, generation=None,
                           settings=get_settings(), council_view=state["view"], recorder=state["recorder"],
                           clock=lambda: ctx.candle_open_time + INTERVAL + 2_000)
    for r in _records(state):
        assert r["information_cutoff_ms"] == ctx.candle_open_time + INTERVAL - 1
        assert r["price_at_signal"] == ctx.close_price and r["price_at_signal_ts_ms"] == r["information_cutoff_ms"]
        assert r["decision_ms"] >= r["information_cutoff_ms"]


@pytest.mark.parametrize("age_ms,stale", [(2_000, False), (5_000, False), (6_000, True), (45_000, True)])
async def test_stale_decisions_are_rejected(db_session, shadow_on, age_ms, stale):
    _, state = shadow_on
    _, candles, ctx = await _ctx(db_session)
    cutoff = ctx.candle_open_time + INTERVAL - 1
    state["book"] = FakeBook(mid=ctx.close_price)
    await run_shadow_cycle(bind=db_session.bind, context=ctx, prev_context=None, candles=candles, generation=None,
                           settings=get_settings(), council_view=state["view"], recorder=state["recorder"],
                           book_provider=state["book"], clock=lambda: cutoff + age_ms)
    rows = _records(state)
    assert rows and all(("decision_too_old" in r["gate_rejection_reasons"]) is stale for r in rows)
    assert all(r["would_trade"] is (not stale) for r in rows)


@pytest.mark.parametrize("move_bps,rejected", [(5.0, False), (-5.0, False), (20.0, True), (-20.0, True)])
async def test_price_drift_rejection_both_directions(db_session, shadow_on, move_bps, rejected):
    _, state = shadow_on
    _, candles, ctx = await _ctx(db_session)
    cutoff = ctx.candle_open_time + INTERVAL - 1
    state["book"] = FakeBook(mid=ctx.close_price * (1 + move_bps / 1e4), half_spread=0.0005)
    await run_shadow_cycle(bind=db_session.bind, context=ctx, prev_context=None, candles=candles, generation=None,
                           settings=get_settings(), council_view=state["view"], recorder=state["recorder"],
                           book_provider=state["book"], clock=lambda: cutoff + 1_000)
    rows = _records(state)
    assert {r["direction"] for r in rows} == {"LONG", "SHORT"}
    for r in rows:
        assert ("price_moved_too_far" in r["gate_rejection_reasons"]) is rejected
        expected = move_bps if r["direction"] == "LONG" else -move_bps     # + = moved in the trade's favour
        assert r["signed_drift_bps"] == pytest.approx(expected, abs=0.05)
        assert r["absolute_drift_bps"] == pytest.approx(abs(move_bps), abs=0.05)
        assert r["spread_bps"] is not None


async def test_missing_book_is_recorded_not_fabricated(db_session, shadow_on):
    _, state = shadow_on
    _, candles, ctx = await _ctx(db_session)
    await run_shadow_cycle(bind=db_session.bind, context=ctx, prev_context=None, candles=candles, generation=None,
                           settings=get_settings(), council_view=state["view"], recorder=state["recorder"],
                           book_provider=FakeBook(fail=True), clock=lambda: ctx.candle_open_time + INTERVAL + 1_000)
    for r in _records(state):
        assert r["bid"] is None and r["ask"] is None and r["spread_bps"] is None and r["signed_drift_bps"] is None
        assert r["price_source"] == "unavailable" and r["shadow_fill_source"] == "no_observed_price_after_decision"
        assert "spread_not_checked" in r["gate_flags"] and r["expected_move_bps"] is None and r["prompt_version"] is None


# --------------------------------------------------------------------------- 1/2: paper fill timing
def test_first_observed_price_never_precedes_the_decision():
    obs = bar_observations(T0, INTERVAL, open_=100.0, close=101.0)
    assert first_observed_at_or_after(T0 + 3_000, obs).source == "bar_close"          # open was printed before
    assert first_observed_at_or_after(T0, obs).source == "bar_open"
    assert first_observed_at_or_after(T0 + INTERVAL, obs) is None                      # nothing observed after: no fill
    assert first_observed_at_or_after(T0, [PriceObservation(T0 + 1, 1.0, "m", modelled=True)]) is None


async def _two_bar_paper_run(db, monkeypatch, *, decided_after_close_ms):
    s = get_settings()
    monkeypatch.setattr(s, "council_enabled", False)
    monkeypatch.setattr(s, "paper_latency_ms", 0)
    await _seed(db, modes=("long_only",))
    fake = FakeHyperliquid(n_candles=LAST + 2)
    fake.hidden = {T0 + (LAST + 1) * INTERVAL}
    await cycle_mod.run_pending_cycles(db, MarketDataService(fake, clock_ms=lambda: clock_after_bar(LAST)), None,
                                       execution_engine=PaperExecutionAdapter())
    order = (await db.execute(select(Order))).scalars().one()
    assert order.status == OrderStatus.PENDING
    order_id = order.id
    # Test clocks are synthetic: pin the order's WALL-CLOCK decision time to "signal bar close + N ms", as in production.
    order.created_at = datetime.fromtimestamp((T0 + LAST * INTERVAL + INTERVAL + decided_after_close_ms) / 1000, tz=timezone.utc)
    await db.commit()
    fake.hidden = set()
    await cycle_mod.run_pending_cycles(db, MarketDataService(fake, clock_ms=lambda: clock_after_bar(LAST + 1)), None,
                                       execution_engine=PaperExecutionAdapter())
    db.expire_all()
    # the ORIGINAL entry order (the agent may legitimately signal again on the fill bar)
    return (await db.execute(select(Order).where(Order.id == order_id))).scalars().one(), fake


async def test_paper_fill_after_decision_uses_a_later_price_and_timestamp(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "paper_entry_price_source", "first_observed_after_decision")
    order, fake = await _two_bar_paper_run(db_session, monkeypatch, decided_after_close_ms=3_000)
    fill_bar = fake.candles[LAST + 1]
    assert order.status == OrderStatus.FILLED
    assert order.filled_at >= order.created_at                                  # property 2
    assert order.intent["entry_price_source"] == "bar_close"
    assert order.intent["entry_price_ts_ms"] >= order.intent["decided_at_ms"]  # property 1
    slip = order.filled_price / float(fill_bar["c"]) - 1
    assert 0 < slip < 0.001                                                      # close + adverse slippage, not the open
    pos = (await db_session.execute(select(Position))).scalars().one()
    assert pos.opened_at >= order.created_at
    assert pos.last_processed_open_time == fill_bar["t"]                         # no stop/TP on the bar before the fill


async def test_paper_fill_is_cancelled_when_no_price_follows_the_decision(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "paper_entry_price_source", "first_observed_after_decision")
    order, _ = await _two_bar_paper_run(db_session, monkeypatch, decided_after_close_ms=INTERVAL + 5_000)
    assert order.status == OrderStatus.CANCELLED and order.rejection_reason == "no_observed_price_after_decision"
    assert (await db_session.execute(select(Position))).scalars().all() == []


async def test_legacy_next_open_default_is_unchanged(db_session, monkeypatch):
    assert get_settings().paper_entry_price_source == "next_open"
    order, fake = await _two_bar_paper_run(db_session, monkeypatch, decided_after_close_ms=3_000)
    fill_bar = fake.candles[LAST + 1]
    assert order.status == OrderStatus.FILLED
    assert 0 < order.filled_price / float(fill_bar["o"]) - 1 < 0.001             # bar OPEN, exactly as before
    # documents the known optimism this option exists to remove: that price predates the decision
    assert int(fill_bar["t"]) < int(order.created_at.timestamp() * 1000)
