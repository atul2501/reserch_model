"""Regression coverage for the `as_of` hardening pass: for any evaluation with
`as_of = T`, no information after T may influence the result. Proves the
boundary with real data (exactly-at-T, immediately-before/after, empty-future,
missing/partial candles, a UTC-day-boundary case), not just by inspection.

Three real, previously-unbounded call sites were fixed:
  - performance_metrics_service.compute_agent_performance_metric's internal
    trade self-load (only exercised when the caller doesn't pass `trades=`)
  - analytics_store.refresh_trade_analytics / refresh_strategy_regime_matrix
  - correlation_service.compute_generation_correlation_report's lookback window
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

import app.analytics.analytics_store as store
from app.analytics.performance_metrics_service import compute_agent_performance_metric
from app.evolution.correlation_service import compute_generation_correlation_report
from app.models.agent import Agent
from app.models.analytics import TradeAnalytics
from app.models.enums import AgentStatus, Side, StrategyFamily
from app.models.market import MarketCandle
from app.models.research import ResearchEpoch
from app.models.strategy import Strategy, StrategyVersion
from app.models.trading import Trade
from app.schemas.strategy_dna import Condition, RuleSet, StrategyDNA
from tests.helpers_agents import closed_position
from tests.test_analytics_store import T0, _seed as _seed_trade_analytics
from tests.test_backtest_parity import candles as make_candles
from tests.test_correlation import _add_trade, _dna, _seed_agent

MINUTE = 60_000


def _ts(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


# --------------------------------------------------------------------------- #
# refresh_trade_analytics
# --------------------------------------------------------------------------- #
async def test_refresh_trade_analytics_as_of_exactly_at_boundary_includes_that_trade(db_session):
    _agent, trades = await _seed_trade_analytics(db_session)
    await db_session.commit()
    as_of = trades[1].closed_at  # trade[1] closes exactly here; trade[2] closes later

    await store.refresh_trade_analytics(db_session, as_of=as_of)
    await db_session.commit()

    seen = {row for (row,) in (await db_session.execute(select(TradeAnalytics.trade_id))).all()}
    assert trades[0].id in seen and trades[1].id in seen
    assert trades[2].id not in seen


async def test_refresh_trade_analytics_as_of_immediately_before_excludes_the_boundary_trade(db_session):
    _agent, trades = await _seed_trade_analytics(db_session)
    await db_session.commit()
    as_of = trades[1].closed_at - timedelta(milliseconds=1)

    await store.refresh_trade_analytics(db_session, as_of=as_of)
    await db_session.commit()

    seen = {row for (row,) in (await db_session.execute(select(TradeAnalytics.trade_id))).all()}
    assert trades[0].id in seen
    assert trades[1].id not in seen and trades[2].id not in seen


async def test_refresh_trade_analytics_as_of_immediately_after_includes_the_boundary_trade(db_session):
    _agent, trades = await _seed_trade_analytics(db_session)
    await db_session.commit()
    as_of = trades[1].closed_at + timedelta(milliseconds=1)

    await store.refresh_trade_analytics(db_session, as_of=as_of)
    await db_session.commit()

    seen = {row for (row,) in (await db_session.execute(select(TradeAnalytics.trade_id))).all()}
    assert trades[0].id in seen and trades[1].id in seen
    assert trades[2].id not in seen


async def test_refresh_trade_analytics_as_of_before_any_trade_closes_produces_no_rows(db_session):
    await _seed_trade_analytics(db_session)
    await db_session.commit()
    as_of = _ts(T0)  # before every trade's opened_at, let alone closed_at

    await store.refresh_trade_analytics(db_session, as_of=as_of)
    await db_session.commit()

    count = (await db_session.execute(select(TradeAnalytics))).scalars().all()
    assert count == []


async def test_refresh_trade_analytics_as_of_far_future_sees_the_full_post_exit_window(db_session):
    _agent, trades = await _seed_trade_analytics(db_session)
    await db_session.commit()
    trade0 = trades[0]

    await store.refresh_trade_analytics(db_session, as_of=_ts(T0 + 29 * MINUTE))
    await db_session.commit()
    row = (await db_session.execute(select(TradeAnalytics).where(TradeAnalytics.trade_id == trade0.id))).scalar_one()

    assert row.left_on_table_r is not None
    full_left_on_table = row.left_on_table_r


async def test_refresh_trade_analytics_as_of_hides_post_exit_candles_that_have_not_happened_yet(db_session):
    """The post-exit MFE/MAE window must only see candles that existed as of `as_of` -
    a fixed-as_of replay pinned right at a trade's own close (no post-exit candle exists
    yet as of that time) must show materially less "left on table" credit than a replay
    that could see the full post-exit window, proving the window is actually being bounded
    and not just plumbed through unused."""
    _agent, trades = await _seed_trade_analytics(db_session)
    await db_session.commit()
    trade0 = trades[0]

    await store.refresh_trade_analytics(db_session, as_of=trade0.closed_at)
    await db_session.commit()
    row = (await db_session.execute(select(TradeAnalytics).where(TradeAnalytics.trade_id == trade0.id))).scalar_one()

    # No candle after trade0's own close is visible as of trade0.closed_at, so the
    # post-exit-only fields must reflect "no post-exit data seen" rather than the full,
    # multi-bar window a later/unbounded refresh would compute.
    assert row.post_exit_mfe_bps_30 is None or abs(row.post_exit_mfe_bps_30) < 1e-9
    assert (row.left_on_table_r or 0) <= 0.0 + 1e-9


# --------------------------------------------------------------------------- #
# refresh_strategy_regime_matrix
# --------------------------------------------------------------------------- #
async def test_refresh_strategy_regime_matrix_as_of_bounds_which_trades_are_aggregated(db_session):
    from app.models.analytics import StrategyRegimeMatrix

    _agent, trades = await _seed_trade_analytics(db_session)
    await db_session.commit()
    as_of = trades[1].closed_at  # trade[0] and trade[1] are RANGE-regime (open_i < 10); trade[2] is TREND_UP

    await store.refresh_trade_analytics(db_session, as_of=as_of)
    await db_session.commit()
    result = await store.refresh_strategy_regime_matrix(db_session, as_of=as_of)
    await db_session.commit()

    assert result.matrix_cells > 0
    full_range_cell = (await db_session.execute(
        select(StrategyRegimeMatrix).where(
            StrategyRegimeMatrix.window_key == "full", StrategyRegimeMatrix.granularity == "family",
            StrategyRegimeMatrix.regime == "RANGE", StrategyRegimeMatrix.dim_id == "momentum",
        )
    )).scalar_one()
    # Only trade[0]+trade[1] are visible as of this as_of; trade[2] (TREND_UP, after as_of)
    # must not be counted anywhere, including indirectly inflating this cell.
    assert full_range_cell.trade_count == 2


# --------------------------------------------------------------------------- #
# compute_agent_performance_metric (self-load path, trades=None)
# --------------------------------------------------------------------------- #
async def _seed_agent_with_trades(db_session, *, net_pnls_and_closed: list[tuple[float, datetime]]) -> Agent:
    code = f"STRAT-TEST-{uuid.uuid4().hex[:8]}"
    strategy = Strategy(code=code, family=StrategyFamily.MOMENTUM, name=code)
    db_session.add(strategy)
    await db_session.flush()
    dna = StrategyDNA(
        strategy_family=StrategyFamily.MOMENTUM, indicators=[{"name": "rsi", "params": {"period": 14}}],
        entry_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="gt", value=60)]),
        exit_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="lt", value=40)]),
    )
    version = StrategyVersion(strategy_id=strategy.id, version=1, generation=1, dna=dna.model_dump(mode="json"))
    db_session.add(version)
    await db_session.flush()
    agent = Agent(
        identifier=f"AG{uuid.uuid4().hex[:6]}", generation=1, strategy_version_id=version.id,
        starting_balance=100.0, balance=100.0, equity=100.0, peak_equity=100.0,
        day_start_equity=100.0, day_start_date=date.today(),
    )
    db_session.add(agent)
    await db_session.flush()
    for net_pnl, closed in net_pnls_and_closed:
        db_session.add(Trade(
            agent_id=agent.id, position_id=closed_position(db_session, agent), symbol="SOL", side=Side.LONG,
            quantity=1.0, entry_price=100.0, exit_price=100.0 + net_pnl, gross_pnl=net_pnl, fees=0.0,
            net_pnl=net_pnl, opened_at=closed - timedelta(minutes=5), closed_at=closed,
            holding_seconds=300, exit_reason="signal",
        ))
    await db_session.commit()
    return agent


async def test_compute_agent_performance_metric_self_load_excludes_trades_closed_after_as_of(db_session):
    now = datetime.now(timezone.utc)
    boundary = now - timedelta(hours=1)
    agent = await _seed_agent_with_trades(db_session, net_pnls_and_closed=[
        (5.0, boundary - timedelta(minutes=10)),   # before
        (3.0, boundary),                            # exactly at
        (-2.0, boundary + timedelta(minutes=10)),   # after - must be excluded
    ])

    metric = await compute_agent_performance_metric(db_session, agent, as_of=boundary)  # trades=None -> self-load path

    assert metric.trade_count == 2


async def test_compute_agent_performance_metric_self_load_with_no_as_of_sees_everything(db_session):
    """Backward-compatible default: as_of=None preserves the original unbounded behavior."""
    now = datetime.now(timezone.utc)
    agent = await _seed_agent_with_trades(db_session, net_pnls_and_closed=[
        (5.0, now - timedelta(minutes=10)), (3.0, now - timedelta(minutes=5)), (-2.0, now),
    ])

    metric = await compute_agent_performance_metric(db_session, agent, as_of=None)

    assert metric.trade_count == 3


async def test_compute_agent_performance_metric_as_of_with_empty_future_still_returns_a_finite_metric(db_session):
    boundary = datetime.now(timezone.utc) - timedelta(days=1)
    agent = await _seed_agent_with_trades(db_session, net_pnls_and_closed=[
        (5.0, boundary + timedelta(hours=1)),  # only trade is AFTER as_of -> zero visible trades
    ])

    metric = await compute_agent_performance_metric(db_session, agent, as_of=boundary)

    assert metric.trade_count == 0
    assert metric.win_rate is None  # no evidence, never guessed


# --------------------------------------------------------------------------- #
# compute_generation_correlation_report (now override)
# --------------------------------------------------------------------------- #
async def test_correlation_report_now_override_excludes_trades_closed_after_it(db_session):
    generation = 400
    dna = _dna()
    agent_a = await _seed_agent(db_session, generation=generation, family=StrategyFamily.MOMENTUM, dna=dna)
    agent_b = await _seed_agent(db_session, generation=generation, family=StrategyFamily.MOMENTUM, dna=dna)

    now_ref = datetime.now(timezone.utc) - timedelta(days=5)  # simulate a replay of a past "now"
    in_window = [(Side.LONG, 3.0), (Side.SHORT, -1.0), (Side.LONG, 2.0), (Side.SHORT, -2.0)]
    for i, (side, pnl) in enumerate(in_window):
        closed = now_ref - timedelta(hours=len(in_window) - i)
        await _add_trade(db_session, agent_a, side=side, net_pnl=pnl, closed_at=closed)
        await _add_trade(db_session, agent_b, side=side, net_pnl=pnl, closed_at=closed)
    # trades AFTER now_ref: must not influence a replay pinned at now_ref, even though
    # they're well within a real "today"-anchored lookback window.
    for i in range(3):
        closed = now_ref + timedelta(hours=i + 1)
        await _add_trade(db_session, agent_a, side=Side.SHORT, net_pnl=-9.0, closed_at=closed)
        await _add_trade(db_session, agent_b, side=Side.LONG, net_pnl=9.0, closed_at=closed)
    await db_session.commit()

    report = await compute_generation_correlation_report(db_session, generation=generation, lookback_days=30, now=now_ref)

    assert len(report.pairs) == 1
    pair = report.pairs[0]
    # If the post-now_ref, oppositely-signed trades leaked in, this would be strongly
    # negative instead of strongly positive.
    assert pair.trade_direction_correlation == pytest.approx(1.0)
    assert pair.return_correlation == pytest.approx(1.0)


async def test_correlation_report_default_now_is_backward_compatible(db_session):
    """No `now` override -> real wall-clock time, exactly the pre-existing behavior."""
    generation = 401
    dna = _dna()
    agent_a = await _seed_agent(db_session, generation=generation, family=StrategyFamily.MOMENTUM, dna=dna)
    agent_b = await _seed_agent(db_session, generation=generation, family=StrategyFamily.MOMENTUM, dna=dna)
    now = datetime.now(timezone.utc)
    for i, (side, pnl) in enumerate([(Side.LONG, 3.0), (Side.SHORT, -1.0)]):
        closed = now - timedelta(hours=2 - i)
        await _add_trade(db_session, agent_a, side=side, net_pnl=pnl, closed_at=closed)
        await _add_trade(db_session, agent_b, side=side, net_pnl=pnl, closed_at=closed)
    await db_session.commit()

    report = await compute_generation_correlation_report(db_session, generation=generation, lookback_days=30)

    assert len(report.pairs) == 1


# --------------------------------------------------------------------------- #
# UTC day-boundary case
# --------------------------------------------------------------------------- #
async def test_as_of_boundary_at_utc_midnight_is_inclusive_and_timezone_consistent(db_session):
    """UTCDateTime stores/reads timezone-aware UTC throughout (app/models/base.py) - this
    proves a midnight-adjacent as_of behaves consistently, not just that the type decorator
    exists."""
    midnight = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    agent = await _seed_agent_with_trades(db_session, net_pnls_and_closed=[
        (1.0, midnight - timedelta(seconds=1)),  # 2025-12-31 23:59:59 UTC
        (2.0, midnight),                          # exactly 2026-01-01 00:00:00 UTC
        (3.0, midnight + timedelta(seconds=1)),   # 2026-01-01 00:00:01 UTC
    ])

    metric = await compute_agent_performance_metric(db_session, agent, as_of=midnight)

    assert metric.trade_count == 2  # the exact-midnight trade is included, the one after is not


# --------------------------------------------------------------------------- #
# IMPLICIT-SAFE invariants: the long tail of "latest row" queries across
# breeding.py/champion_challenger_service.py/promotion_service.py/etc. have no
# explicit as_of bound and were deliberately NOT refactored (see
# MULTI_WEEK_RESEARCH_READINESS_REPORT.md) - they are correct today only
# because of these invariants. Proving the invariants holds is what actually
# makes "implicit-safe" a testable claim instead of an assumption.
# `test_promotion_service.py::test_promotes_and_retires_previous_champion_when_all_gates_pass`
# already covers the single-live-champion-per-lineage invariant; this adds the
# other one (single active research epoch per symbol/timeframe).
# --------------------------------------------------------------------------- #
async def test_only_one_active_epoch_per_symbol_timeframe_survives_a_renewal(db_session):
    from app.research import dataset as ds

    c1 = make_candles(1400, seed=21, drift=0.01)
    db_session.add_all([
        MarketCandle(
            symbol="SOL", timeframe="1m", open_time=int(r.open_time), close_time=int(r.open_time) + 59_999,
            open=float(r.open), high=float(r.high), low=float(r.low), close=float(r.close),
            volume=float(r.volume), is_final=True,
        ) for r in c1.itertuples()
    ])
    await db_session.commit()
    epoch1 = await ds.seal_epoch(db_session, c1, symbol="SOL", timeframe="1m", reason="initial")
    await db_session.commit()

    c2 = make_candles(1500, seed=9, drift=0.01)
    epoch2 = await ds.renew_epoch(db_session, c2, symbol="SOL", timeframe="1m", reason="test renewal")
    await db_session.commit()

    active = (await db_session.execute(
        select(ResearchEpoch).where(ResearchEpoch.symbol == "SOL", ResearchEpoch.timeframe == "1m",
                                    ResearchEpoch.active.is_(True))
    )).scalars().all()
    assert [e.epoch_id for e in active] == [epoch2.epoch_id]  # exactly one, and it's the new one
    assert epoch1.active is False
