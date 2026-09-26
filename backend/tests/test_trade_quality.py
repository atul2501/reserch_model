"""Phase 1 tests: MFE/MAE replay, long/short symmetry, same-bar conservative
ordering, post-exit window, cross-check, classification."""
from __future__ import annotations

from app.analytics import trade_quality as tq

BAR = 60_000


def bar(i: int, o: float, h: float, low: float, c: float) -> tq.Bar:
    return tq.Bar(open_time=1_700_000_000_000 + i * BAR, open=o, high=h, low=low, close=c)


def facts(**over) -> tq.TradeFacts:
    base = dict(
        side="LONG", entry_price=100.0, exit_price=100.0, quantity=10.0,
        opened_at_ms=1_700_000_000_000, closed_at_ms=1_700_000_000_000 + 3 * BAR,
        stop_loss_price=95.0, take_profit_price=110.0,
        persisted_peak_price=None, persisted_trough_price=None,
        entry_bar_open_ms=1_700_000_000_000, exit_reason="stop_loss",
    )
    base.update(over)
    return tq.TradeFacts(**base)


def test_mfe_mae_long_from_replay():
    bars = [bar(0, 100, 102, 99, 101), bar(1, 101, 106, 100.5, 105), bar(2, 105, 105.5, 94.0, 95)]
    ex = tq.analyze_trade(facts(), bars, BAR)
    assert ex.mfe_price == 106.0          # max high of the inclusive window
    assert ex.mae_price == 94.0           # min low
    assert ex.mfe_time_ms == bars[1].open_time   # first bar reaching the final MFE
    assert ex.mae_time_ms == bars[2].open_time
    assert ex.time_to_mfe_seconds == 60
    assert ex.time_to_mae_seconds == 120
    assert ex.mfe_r == pytest_approx(60.0 / 50.0)     # (106-100)*10 / (10*|100-95|)
    assert ex.mae_r == pytest_approx(-60.0 / 50.0)    # (94-100)*10 / (10*|100-95|)
    assert ex.max_unrealized_profit == pytest_approx(60.0)
    assert ex.max_unrealized_loss == pytest_approx(-60.0)


def test_long_short_symmetry():
    # mirrored path: the SHORT of the LONG above, mirrored around 100
    bars_l = [bar(0, 100, 102, 99, 101), bar(1, 101, 106, 100.5, 105), bar(2, 105, 105.5, 94.0, 95)]
    bars_s = [bar(0, 100, 101, 98, 99), bar(1, 99, 99.5, 94, 95), bar(2, 95, 106, 94.5, 105)]
    long = tq.analyze_trade(facts(), bars_l, BAR)
    short = tq.analyze_trade(facts(side="SHORT"), bars_s, BAR)
    assert short.mfe_price == pytest_approx(94.0)      # favourable for a short = the trough
    assert short.mae_price == pytest_approx(106.0)
    assert short.mfe_r == pytest_approx(long.mfe_r)
    assert short.mae_r == pytest_approx(long.mae_r)
    assert short.max_unrealized_profit == pytest_approx(long.max_unrealized_profit)
    assert short.max_unrealized_loss == pytest_approx(long.max_unrealized_loss)


def test_same_bar_conservative_ordering():
    # one bar that BOTH extends +1R and hits the -1R stop: the engine assumes adverse first
    risk = 50.0  # qty 10 * |100-95|
    b0 = bar(0, 100, 105.0, 95.0, 96)
    ex = tq.analyze_trade(facts(closed_at_ms=b0.open_time + BAR - 1), [b0], BAR)
    assert ex.mfe_r == pytest_approx(risk / risk)       # the excursion still sees the high
    assert ex.mae_r == pytest_approx(-risk / risk)
    assert ex.mfe_before_mae is False                    # conservative: adverse first


def test_mfe_before_mae_ordering():
    favourable_first = [bar(0, 100, 102.5, 99, 102), bar(1, 102, 103, 96, 96)]   # +0.5R then -0.8R...
    ex = tq.analyze_trade(facts(), favourable_first, BAR)
    assert ex.mfe_before_mae is True


def test_post_exit_window_and_left_on_table():
    # trade closes on bar 0 at 100; bars 1..3 rally to 103 (favourable for the long)
    bars = [bar(0, 100, 100.5, 99.5, 100), bar(1, 100, 101, 99.5, 101),
            bar(2, 101, 103, 100.9, 102.9), bar(3, 102.9, 103, 102.5, 102.6)]
    ex = tq.analyze_trade(
        facts(exit_reason="exit_rules", exit_price=100.0, closed_at_ms=bars[0].open_time + BAR - 1),
        bars, BAR,
    )
    assert ex.post_exit_mfe_bps == pytest_approx(300.0)     # (103-100)*10 / (10*100) * 1e4 = 300 bps
    assert ex.left_on_table_r == pytest_approx(30.0 / 50.0)


def test_crosscheck_against_persisted_extremes():
    bars = [bar(0, 100, 102, 99, 101), bar(1, 101, 106, 100.5, 105), bar(2, 105, 105.5, 94.0, 95)]
    # persisted extremes cover [entry, exit) = bars 0..1 (the exit bar is never advanced)
    ex = tq.analyze_trade(facts(persisted_peak_price=106.0, persisted_trough_price=99.0), bars, BAR)
    assert ex.replay_peak == 106.0 and ex.replay_trough == 99.0
    assert ex.peak_crosscheck_ok is True
    assert ex.trough_crosscheck_ok is True

    mismatch = tq.analyze_trade(facts(persisted_peak_price=104.0, persisted_trough_price=99.0), bars, BAR)
    assert mismatch.peak_crosscheck_ok is False        # reported, never hidden


def test_crosscheck_skipped_without_persisted_values():
    ex = tq.analyze_trade(facts(persisted_peak_price=None, persisted_trough_price=None),
                          [bar(0, 100, 102, 99, 101)], BAR)
    assert ex.peak_crosscheck_ok is None and ex.trough_crosscheck_ok is None


def test_classification_taxonomy():
    def _ex(mfe_r: float | None, mae_r: float | None, before: bool | None) -> tq.ExcursionResult:
        return make_ex(mfe_r=mfe_r, mae_r=mae_r, mfe_before_mae=before)

    # TP hit
    assert tq.classify_trade(facts(exit_reason="take_profit"), _ex(2.0, -0.2, True),
                             gross_pnl=5.0, net_pnl=4.0) == tq.TAKE_PROFIT_HIT
    # immediate stop: never went anywhere
    assert tq.classify_trade(facts(exit_reason="stop_loss"), _ex(0.1, -1.0, False),
                             gross_pnl=-5.0, net_pnl=-5.0) == tq.STOP_IMMEDIATE
    # reversal: +1.5R MFE then stopped
    assert tq.classify_trade(facts(exit_reason="stop_loss"), _ex(1.5, -1.0, True),
                             gross_pnl=-5.0, net_pnl=-5.0) == tq.REVERSAL_AFTER_PROFIT
    # costs ate a gross winner
    assert tq.classify_trade(facts(exit_reason="exit_rules"), _ex(0.5, -0.2, True),
                             gross_pnl=1.0, net_pnl=-0.2) == tq.COST_EATEN
    # plain stop, neither immediate nor reversal
    assert tq.classify_trade(facts(exit_reason="stop_loss"), _ex(0.5, -1.0, True),
                             gross_pnl=-5.0, net_pnl=-5.0) == tq.STOP_LOSS_OTHER
    # signal exits
    assert tq.classify_trade(facts(exit_reason="exit_rules"), _ex(0.5, -0.2, True),
                             gross_pnl=1.0, net_pnl=0.5) == tq.SIGNAL_EXIT_WIN
    assert tq.classify_trade(facts(exit_reason="exit_rules"), _ex(0.2, -0.5, False),
                             gross_pnl=-1.0, net_pnl=-1.2) == tq.SIGNAL_EXIT_LOSS
    # rollover/liquidation take precedence
    assert tq.classify_trade(facts(exit_reason="generation_rollover"), _ex(1.5, -1.0, True),
                             gross_pnl=-5.0, net_pnl=-5.0) == tq.ROLLOVER
    assert tq.classify_trade(facts(exit_reason="liquidation"), _ex(0.0, -2.0, False),
                             gross_pnl=-50.0, net_pnl=-50.0) == tq.LIQUIDATED


def test_no_stop_means_no_r_but_bps_still_defined():
    ex = tq.analyze_trade(facts(stop_loss_price=None, take_profit_price=None),
                          [bar(0, 100, 102, 99, 101)], BAR)
    assert ex.mfe_r is None and ex.mae_r is None
    assert ex.mfe_bps == pytest_approx(200.0)     # (102-100)*10/(10*100)*1e4
    assert ex.mfe_before_mae is None


def test_entry_only_window_when_exit_equals_entry_bar():
    b0 = bar(0, 100, 101, 99, 100.5)
    ex = tq.analyze_trade(facts(closed_at_ms=b0.open_time + BAR - 1), [b0], BAR)
    assert ex.replay_peak == 100.0 and ex.replay_trough == 100.0    # managed window is empty


# --------------------------------------------------------------------------- #
def make_ex(**over) -> tq.ExcursionResult:
    base = dict(
        mfe_price=100.0, mae_price=100.0, mfe_time_ms=0, mae_time_ms=0,
        time_to_mfe_seconds=0, time_to_mae_seconds=0, mfe_r=None, mae_r=None,
        mfe_bps=0.0, mae_bps=0.0, max_unrealized_profit=0.0, max_unrealized_loss=0.0,
        mfe_before_mae=None, post_exit_mfe_bps=None, post_exit_mae_bps=None,
        left_on_table_r=None, replay_peak=None, replay_trough=None,
        peak_crosscheck_ok=None, trough_crosscheck_ok=None, exit_bar_open_ms=0,
    )
    base.update(over)
    return tq.ExcursionResult(**base)


def pytest_approx(x):
    from pytest import approx

    return approx(x)