"""Walk-forward uses the same execution/risk assumptions as the live research engine (spec phase 16)."""
from __future__ import annotations

import pytest

from app.backtesting.engine import run_backtest
from app.backtesting.walk_forward import run_walk_forward
from app.core.config import get_settings
from app.schemas.strategy_dna import PositionSizing, RiskProfile
from tests.test_backtest_parity import KW, candles, ema_cross_dna

WF = dict(symbol="SOL", timeframe="1m", train_window=300, test_window=200, step=200, starting_equity=100.0,
          fee_rate=0.00045, slippage_bps=2.0)


def _funding(c):
    t0 = int(c["open_time"].iloc[0])
    return [(t0 + h * 1_800_000, 0.0004) for h in range(1, 60)]      # a settlement every 30 minutes


def test_each_window_equals_a_direct_backtest_under_the_same_assumptions():
    c = candles(n=900, seed=21, vol=0.4)
    dna = ema_cross_dna(5, 20)
    funding = _funding(c)
    report = run_walk_forward(c, dna, funding=funding, **WF)
    assert report.windows
    s = get_settings()
    for w in report.windows:
        direct = run_backtest(
            c, dna, symbol="SOL", timeframe="1m", starting_equity=100.0, fee_rate=0.00045, slippage_bps=2.0,
            enforce_risk_engine=True, global_max_leverage=s.max_leverage, global_max_position_size=s.max_position_size,
            global_max_drawdown=s.max_drawdown, global_max_daily_loss=s.max_daily_loss, funding=funding,
            start_index=w.test_start, end_index=w.test_end,
        )
        assert [(t.entry_index, t.exit_index, t.exit_reason) for t in w.result.trades] == \
               [(t.entry_index, t.exit_index, t.exit_reason) for t in direct.trades]
        assert w.result.final_equity == pytest.approx(direct.final_equity, rel=1e-12)


def test_walk_forward_charges_funding():
    c = candles(n=900, seed=22, vol=0.4)
    dna = ema_cross_dna(5, 20)
    with_f = run_walk_forward(c, dna, funding=_funding(c), **WF)
    without = run_walk_forward(c, dna, **WF)
    assert sum(w.result.total_funding for w in with_f.windows) != 0.0
    assert sum(w.result.total_funding for w in without.windows) == 0.0
    assert with_f.average_return_pct != without.average_return_pct


def test_walk_forward_enforces_the_risk_engine_by_default():
    """A DNA that asks for far more than the global caps allow: the risk engine must clamp it in walk-forward too."""
    c = candles(n=900, seed=23, vol=0.4)
    greedy = ema_cross_dna(5, 20, position_sizing=PositionSizing(fraction_of_equity=0.95),
                           risk_profile=RiskProfile(max_leverage=5.0, max_position_fraction=1.0), leverage_limit=5.0)
    enforced = run_walk_forward(c, greedy, **WF)
    unchecked = run_walk_forward(c, greedy, enforce_risk_engine=False, **WF)
    big = lambda rep: max((t.quantity * 100 for w in rep.windows for t in w.result.trades), default=0.0)   # noqa: E731
    assert big(enforced) < big(unchecked)                 # capped by the global exposure/position limits
    assert big(enforced) <= get_settings().max_exposure_multiple * 100 * 1.5


def test_walk_forward_reuses_shared_data_without_recomputing(monkeypatch):
    from app.backtesting import walk_forward as wf
    from app.backtesting.data import prepare_backtest_data
    from app.strategies.engine import dna_indicator_specs

    c = candles(n=900, seed=24)
    dna = ema_cross_dna(5, 20)
    data = prepare_backtest_data(c, symbol="SOL", timeframe="1m", specs=dna_indicator_specs(dna))
    monkeypatch.setattr(wf, "prepare_backtest_data", lambda *a, **k: (_ for _ in ()).throw(AssertionError("recomputed")))
    assert run_walk_forward(c, dna, data=data, **WF).windows
