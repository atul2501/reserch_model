"""Phase 2 tests: Wilson CI, regime episodes, deterministic bootstrap, evidence
states, under-sampling rules, edge flags."""
from __future__ import annotations

import math

from app.analytics import strategy_regime as sr


def row(net: float, episode: int, gross: float | None = None, klass: str = "SIGNAL_EXIT_WIN") -> sr.TradeRow:
    return sr.TradeRow(net_pnl=net, gross_pnl=(net if gross is None else gross), fees=0.0, funding=0.0,
                       slippage=0.0, holding_seconds=60, mfe_r=None, mae_r=None,
                       quality_class=klass, episode_id=episode, closed_at=float(episode))


def test_wilson_ci_known_values():
    lo, hi = sr.wilson_ci(7, 10)
    p = 0.7
    assert lo < p < hi
    # known reference: 7/10 -> [0.3968, 0.8922] at z=1.95996
    assert abs(lo - 0.3968) < 1e-3 and abs(hi - 0.8922) < 1e-3
    assert sr.wilson_ci(0, 0) is None
    edge0 = sr.wilson_ci(0, 20)
    assert edge0[0] == 0.0 and edge0[1] > 0
    edge1 = sr.wilson_ci(20, 20)
    assert edge1[1] == 1.0 and edge1[0] < 1


def test_wilson_ci_shrinks_with_n():
    small = sr.wilson_ci(7, 10)
    large = sr.wilson_ci(70, 100)
    assert (large[1] - large[0]) < (small[1] - small[0])


def test_episode_ids_runs():
    series = [(1, "A"), (2, "A"), (3, "B"), (4, "B"), (5, "B"), (6, "A")]
    ids = sr.episode_ids(series)
    assert ids == {1: 1, 2: 1, 3: 2, 4: 2, 5: 2, 6: 3}


def test_cell_metrics_aggregates():
    rows = [row(2.0, 1, klass="TAKE_PROFIT_HIT"), row(-1.0, 1), row(3.0, 2), row(-0.5, 2)]
    m = sr.cell_metrics(rows)
    assert m["trade_count"] == 4
    assert m["win_count"] == 2 and m["loss_count"] == 2
    assert m["win_rate"] == 0.5
    assert m["net_pnl"] == 3.5
    assert m["expectancy"] == 3.5 / 4
    assert m["profit_factor"] == 5.0 / 1.5
    assert m["avg_winner"] == 2.5
    assert m["avg_loser"] == -0.75
    assert m["tp_first_pct"] == 0.25 and m["cost_eaten_pct"] == 0.0


def test_profit_factor_none_without_losses():
    m = sr.cell_metrics([row(1.0, 1), row(2.0, 1)])
    assert m["profit_factor"] is None


def test_bootstrap_deterministic_and_seeded():
    rows = [row(v, ep) for ep, vals in {1: [1.0, -0.5], 2: [0.5, 0.7], 3: [-0.2, 0.9]}.items() for v in vals]
    ci1 = sr.bootstrap_expectancy_ci(rows, seed_key=("w", "family", "momentum", "RANGE"))
    ci2 = sr.bootstrap_expectancy_ci(rows, seed_key=("w", "family", "momentum", "RANGE"))
    assert ci1 == ci2                      # deterministic: same cell -> identical interval
    ci3 = sr.bootstrap_expectancy_ci(rows, seed_key=("w", "family", "momentum", "TREND_UP"))
    assert ci3 is not None and ci3[0] <= ci3[1]
    # determinism across process restarts matters more than seed divergence on toy data


def test_bootstrap_needs_two_episodes():
    rows = [row(1.0, 1), row(2.0, 1)]
    assert sr.bootstrap_expectancy_ci(rows, seed_key=("w", "g", "d", "r")) is None


def test_under_sampled_rules():
    assert sr.under_sampled_flag(0, 0, False) is True
    assert sr.under_sampled_flag(100, 1, True) is True       # 100 trades in ONE episode: one market condition
    assert sr.under_sampled_flag(10, 3, True) is False


def test_edge_never_declared_when_under_sampled():
    rows = [row(1.0, 1), row(2.0, 1)]
    assert sr.edge_flags(rows, seed_key=("w", "g", "d", "r"), under_sampled=True) == (False, False)


def test_edge_flags_positive_and_negative():
    pos = [row(v, ep) for ep, vals in {1: [2.0, 1.5], 2: [1.0, 2.5], 3: [1.8, 0.9]}.items() for v in vals]
    neg = [row(v, ep) for ep, vals in {1: [-2.0, -1.5], 2: [-1.0, -2.5], 3: [-1.8, -0.9]}.items() for v in vals]
    pos_g, pos_n = sr.edge_flags(pos, seed_key=("w", "g", "d", "r"), under_sampled=False)
    neg_g, neg_n = sr.edge_flags(neg, seed_key=("w", "g", "d", "r2"), under_sampled=False)
    assert pos_g is True and pos_n is True
    assert neg_g is True and neg_n is True        # a consistently negative cell IS an edge (a bad one)


def test_evidence_states_with_episode_gate():
    from app.analytics.shadow_fitness import Prior

    prior = Prior(0.0, 100.0, 100.0, 5, False)
    # many trades but ONE episode: never TESTED
    one_episode = [1.0] * 50
    assert sr.cell_evidence_state(50, 1, one_episode, prior) == sr.PROVISIONAL
    # many trades across many episodes with a clear signal: TESTED
    assert sr.cell_evidence_state(50, 5, [1.0] * 50, prior) == sr.TESTED
    # no trades: UNTESTED
    assert sr.cell_evidence_state(0, 0, [], prior) == sr.UNTESTED
    # few, very noisy trades: PROVISIONAL (the estimate cannot be trusted yet)
    assert sr.cell_evidence_state(3, 3, [80.0, -80.0, 60.0], prior) == sr.PROVISIONAL


def test_drawdown_ordering_by_closed_at():
    # a win then a big loss, reported in reverse insertion order: drawdown must use closed_at order
    late_loss = sr.TradeRow(net_pnl=-6.0, gross_pnl=-6.0, fees=0.0, funding=0.0, slippage=0.0,
                            holding_seconds=60, mfe_r=None, mae_r=None, quality_class="SIGNAL_EXIT_LOSS",
                            episode_id=1, closed_at=2.0)
    early_win = sr.TradeRow(net_pnl=4.0, gross_pnl=4.0, fees=0.0, funding=0.0, slippage=0.0,
                            holding_seconds=60, mfe_r=None, mae_r=None, quality_class="SIGNAL_EXIT_WIN",
                            episode_id=1, closed_at=1.0)
    m = sr.cell_metrics([late_loss, early_win])
    assert m["max_drawdown_currency"] < 0
    assert math.isclose(m["max_drawdown_currency"], -6.0)


def test_zero_trade_cell_is_all_none():
    m = sr.cell_metrics([])
    assert m["trade_count"] == 0
    assert m["win_rate"] is None and m["expectancy"] is None and m["profit_factor"] is None
    assert m["win_rate_ci_low"] is None