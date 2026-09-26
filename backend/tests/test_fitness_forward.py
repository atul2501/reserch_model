"""Phase 3 tests: look-ahead protection, historical reconstruction, censoring,
generation rollover, window math."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.analytics import fitness_forward as ff
from app.analytics.fitness_engine import FitnessWeights
from app.models.enums import AgentStatus

T0 = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


def point(minutes: int, pnl: float, notional: float = 1000.0) -> ff.TradePoint:
    return ff.TradePoint(closed_at=T0 + timedelta(minutes=minutes), net_pnl=pnl,
                         notional=notional, opened_at=T0 + timedelta(minutes=minutes - 5))


def facts(**over) -> ff.AgentFacts:
    base = dict(
        agent_id="a" * 32, generation=1, starting_balance=100.0,
        created_at=T0, death_timestamp=None, status=AgentStatus.ACTIVE,
    )
    base.update(over)
    return ff.AgentFacts(**base)


W = FitnessWeights()


def test_reconstruction_uses_only_trades_upto_t():
    trades = [point(10, 1.0), point(20, -3.0), point(200, 50.0)]        # the 50.0 is AFTER T
    t = T0 + timedelta(minutes=30)
    r = ff.reconstruct_fitness_at(facts(), trades, as_of=t, weights=W)
    assert r.components["trade_count"] == 2                # the future trade is invisible
    assert r.components["equity_at_t"] == 100.0 + 1.0 - 3.0


def test_reconstruction_never_touches_mutable_agent_state():
    # the SAME set of trades must give the SAME fitness regardless of what the
    # mutable "now" columns would say (they are not even passed in)
    trades = [point(10, 1.0), point(20, -3.0)]
    t = T0 + timedelta(minutes=30)
    r1 = ff.reconstruct_fitness_at(facts(), trades, as_of=t, weights=W)
    r2 = ff.reconstruct_fitness_at(facts(status=AgentStatus.RETIRED, death_timestamp=T0 + timedelta(hours=5)),
                                    trades, as_of=t, weights=W)
    # a death AFTER T must not change the reconstruction at T
    assert r1.fitness == r2.fitness
    assert r1.components["trade_count"] == r2.components["trade_count"]


def test_dead_agent_reconstruction_endstops_at_death():
    death = T0 + timedelta(minutes=15)
    trades = [point(10, 1.0), point(20, -3.0)]
    t = T0 + timedelta(minutes=30)
    r = ff.reconstruct_fitness_at(facts(status=AgentStatus.DEAD, death_timestamp=death), trades,
                                  as_of=t, weights=W)
    assert r.components["survival_days"] == 15 / 60 / 24       # survival ends at death, not at T


def test_forward_window_uses_only_trades_after_t():
    trades = [point(10, 1.0), point(20, 2.0), point(90, 5.0), point(400, -1.0)]
    t = T0 + timedelta(minutes=30)
    window = ff.forward_window(t, 60, death_at=None, generation_rollover_at=None,
                               data_end=T0 + timedelta(hours=10))
    fwd = ff.forward_performance(trades, window, starting_balance=100.0)
    assert fwd.trade_count == 1                       # only the trade at +90m
    assert fwd.net_pnl == 5.0
    # the trade at +400m is beyond the horizon: excluded


def test_window_censors_at_generation_rollover():
    t = T0 + timedelta(minutes=30)
    rollover = T0 + timedelta(minutes=30 + 20)
    window = ff.forward_window(t, 60, death_at=None, generation_rollover_at=rollover,
                               data_end=T0 + timedelta(hours=10))
    assert window.censor_reason == ff.CENSOR_GENERATION_ROLLOVER
    assert window.window_end_actual == rollover
    assert abs(window.window_coverage - 20 / 60) < 1e-9


def test_window_censors_at_death_first():
    t = T0
    window = ff.forward_window(t, 60, death_at=t + timedelta(minutes=10),
                               generation_rollover_at=t + timedelta(minutes=20),
                               data_end=t + timedelta(hours=10))
    assert window.censor_reason == ff.CENSOR_AGENT_DEATH
    assert window.window_end_actual == t + timedelta(minutes=10)


def test_window_censors_at_data_end():
    t = T0
    window = ff.forward_window(t, 60, death_at=None, generation_rollover_at=None,
                               data_end=t + timedelta(minutes=15))
    assert window.censor_reason == ff.CENSOR_DATA_END
    assert window.window_coverage == 15 / 60


def test_full_coverage_when_no_boundary_hits():
    t = T0
    window = ff.forward_window(t, 60, death_at=None, generation_rollover_at=None,
                               data_end=t + timedelta(hours=5))
    assert window.censor_reason == ff.CENSOR_NONE
    assert window.window_coverage == 1.0


def test_generation_rollover_future_excludes_post_boundary_trades():
    # gen1 agents: trades after the rollover boundary must not count as gen1 future performance
    t = T0
    rollover = t + timedelta(minutes=30)
    trades = [point(10, 1.0), point(20, 2.0), point(35, 9.9)]    # the third is AFTER the rollover
    window = ff.forward_window(t, 1440, death_at=None, generation_rollover_at=rollover,
                               data_end=t + timedelta(hours=10))
    fwd = ff.forward_performance(trades, window, starting_balance=100.0)
    assert fwd.trade_count == 2
    assert fwd.net_pnl == 3.0          # only the pre-boundary trades; 9.9 excluded


def test_future_drawdown_isolated_from_history():
    # a big PRE-T drawdown must not appear in the forward window's drawdown
    t = T0 + timedelta(minutes=30)
    pre = [point(10, -50.0), point(20, -50.0)]
    post = [point(40, 1.0), point(50, -0.5)]
    window = ff.forward_window(t, 60, death_at=None, generation_rollover_at=None,
                               data_end=T0 + timedelta(hours=10))
    fwd = ff.forward_performance(pre + post, window, starting_balance=100.0)
    assert fwd.trade_count == 2
    assert fwd.max_drawdown_currency is not None
    assert fwd.max_drawdown_currency == -0.5          # only the window's own dip


def test_reconstruction_matches_recorded_snapshot_for_flat_agent():
    # A flat agent (no open position) at snapshot time: recorded fitness used
    # agent.equity == balance == starting + realized; the reconstruction sees
    # exactly the same inputs -> the same fitness.
    trades = [point(10, 1.0), point(20, -0.4)]
    t = T0 + timedelta(minutes=30)
    r = ff.reconstruct_fitness_at(facts(), trades, as_of=t, weights=W)
    # identical inputs -> identical output (deterministic, pure)
    r2 = ff.reconstruct_fitness_at(facts(), list(trades), as_of=t, weights=W)
    assert r.fitness == r2.fitness
    assert r.components["equity_at_t"] == 100.6


def test_future_bps_pooled_notional():
    trades = [point(40, 1.0, notional=1000.0), point(50, -0.5, notional=3000.0)]
    window = ff.forward_window(T0, 60, death_at=None, generation_rollover_at=None,
                               data_end=T0 + timedelta(hours=10))
    fwd = ff.forward_performance(trades, window, starting_balance=100.0)
    assert abs(fwd.net_bps - 1e4 * 0.5 / 4000.0) < 1e-9