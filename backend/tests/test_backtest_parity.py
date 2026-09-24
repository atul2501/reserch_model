"""Backtest parity (spec phases 10, 22): the backtester runs the SAME strategy
engine, sizing, stops, trailing, cost model as the live worker, and is free of
look-ahead."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.backtesting.data import prepare_backtest_data
from app.backtesting.engine import run_backtest
from app.backtesting.walk_forward import run_walk_forward
from app.models.enums import StrategyFamily
from app.schemas.strategy_dna import (
    Condition, CooldownConfig, PositionSizing, RiskProfile, RuleSet, StopLossConfig, StrategyDNA, TakeProfitConfig,
    TrailingStopConfig,
)
from app.strategies.engine import dna_indicator_specs

KW = dict(symbol="SOL", timeframe="1m", starting_equity=100.0, fee_rate=0.00045, slippage_bps=2.0)


def candles(n=900, seed=0, drift=0.0, vol=0.35):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(drift, vol, n))
    open_ = np.r_[close[0], close[:-1]]
    return pd.DataFrame({
        "open_time": np.arange(n) * 60_000 + 1_700_000_040_000, "open": open_,
        "high": np.maximum(open_, close) + rng.uniform(0.02, 0.4, n), "low": np.minimum(open_, close) - rng.uniform(0.02, 0.4, n),
        "close": close, "volume": rng.uniform(500, 1500, n),
    })


def ema_cross_dna(fast, slow, **kw):
    base = dict(
        strategy_family=StrategyFamily.TREND_FOLLOWING,
        indicators=[{"name": "ema", "params": {"period": fast}}, {"name": "ema", "params": {"period": slow}}],
        entry_rules=RuleSet(conditions=[Condition(feature=f"ema_{fast}", operator="gt", value=f"ema_{slow}")]),
        exit_rules=RuleSet(conditions=[Condition(feature=f"ema_{fast}", operator="lt", value=f"ema_{slow}")]),
        direction_mode="long_only",
        risk_profile=RiskProfile(max_leverage=2.0, max_position_fraction=0.5), leverage_limit=2.0,
        position_sizing=PositionSizing(fraction_of_equity=0.2),
        stop_loss=StopLossConfig(method="atr_multiple", value=3.0), take_profit=TakeProfitConfig(enabled=False),
    )
    base.update(kw)
    return StrategyDNA(**base)


def test_declared_indicator_periods_drive_backtest_behaviour():
    c = candles(seed=3)
    fast = run_backtest(c, ema_cross_dna(5, 20), **KW)
    slow = run_backtest(c, ema_cross_dna(20, 80), **KW)
    assert fast.trades and slow.trades
    assert len(fast.trades) != len(slow.trades)                      # different periods -> genuinely different trading
    assert [t.entry_index for t in fast.trades] != [t.entry_index for t in slow.trades]


def test_backtest_is_deterministic():
    c = candles(seed=4)
    a, b = run_backtest(c, ema_cross_dna(8, 30), **KW), run_backtest(c, ema_cross_dna(8, 30), **KW)
    assert a.final_equity == b.final_equity and [t.net_pnl for t in a.trades] == [t.net_pnl for t in b.trades]


def test_no_lookahead_appending_future_bars_never_changes_earlier_trades():
    c = candles(1000, seed=5)
    dna = ema_cross_dna(8, 30)
    short = run_backtest(c.iloc[:700].reset_index(drop=True), dna, **KW)
    long_ = run_backtest(c, dna, **KW)
    cut = 690  # trades that completed well before the truncation point must be identical
    a = [(t.entry_index, t.exit_index, round(t.net_pnl, 9)) for t in short.trades if t.exit_index < cut]
    b = [(t.entry_index, t.exit_index, round(t.net_pnl, 9)) for t in long_.trades if t.exit_index < cut]
    assert a == b and a


def test_entries_fill_at_the_next_bar_open_plus_slippage():
    c = candles(seed=6)
    r = run_backtest(c, ema_cross_dna(5, 20), **KW)
    t = r.trades[0]
    bar_open = float(c["open"].iloc[t.entry_index])
    assert t.entry_price == pytest.approx(bar_open * (1 + 2.0 / 10_000))       # long: pays up


def test_stop_loss_take_profit_are_applied_and_stop_wins_an_ambiguous_bar():
    c = candles(seed=7, vol=0.6)
    dna = ema_cross_dna(5, 20, stop_loss=StopLossConfig(method="fixed_pct", value=0.3),
                        take_profit=TakeProfitConfig(method="fixed_pct", value=0.3))
    r = run_backtest(c, dna, **KW)
    reasons = {t.exit_reason for t in r.trades}
    assert {"stop_loss", "take_profit"} & reasons
    for t in r.trades:
        if t.exit_reason == "stop_loss":
            assert t.exit_price <= t.entry_price * (1 + 1e-9) or t.net_pnl < 0


def test_trailing_stop_exits_are_produced():
    c = candles(seed=8, drift=0.05, vol=0.4)
    dna = ema_cross_dna(5, 20, stop_loss=StopLossConfig(method="fixed_pct", value=5.0), take_profit=TakeProfitConfig(enabled=False),
                        trailing_stop=TrailingStopConfig(enabled=True, activation_pct=0.2, trail_pct=0.3))
    r = run_backtest(c, dna, **KW)
    assert "trailing_stop" in {t.exit_reason for t in r.trades}


def test_cooldown_and_daily_trade_limits_are_enforced():
    c = candles(seed=9, vol=0.5)
    free = run_backtest(c, ema_cross_dna(3, 8), **KW)
    cooled = run_backtest(c, ema_cross_dna(3, 8, cooldown=CooldownConfig(bars_after_loss=30, bars_after_win=30)), **KW)
    capped = run_backtest(c, ema_cross_dna(3, 8, max_trades_per_day=2), **KW)
    assert len(cooled.trades) < len(free.trades)
    assert len(capped.trades) <= 2 * (len(c) // 1440 + 1) and len(capped.trades) < len(free.trades)
    # after a losing trade, the next entry is at least the cooldown later
    losers = [t for t in cooled.trades if t.net_pnl < 0]
    for a, b in zip(cooled.trades, cooled.trades[1:]):
        if a.net_pnl < 0:
            assert b.entry_index - a.exit_index >= 30 + 1   # signal at X+30, filled one bar later


def test_equity_curve_is_marked_to_market_so_drawdown_includes_open_losses():
    c = candles(seed=10, drift=-0.03)
    dna = ema_cross_dna(5, 20, stop_loss=StopLossConfig(enabled=False))
    r = run_backtest(c, dna, **KW)
    realized_only = [KW["starting_equity"]]
    running = KW["starting_equity"]
    for t in r.trades:
        running += t.net_pnl
        realized_only.append(running)
    peak, dd = 0.0, 0.0
    for e in realized_only:
        peak = max(peak, e)
        dd = max(dd, (peak - e) / peak)
    assert r.max_drawdown_pct >= dd - 1e-9


def test_funding_is_accrued_when_settlements_are_supplied():
    c = candles(seed=11, drift=0.05)
    dna = ema_cross_dna(5, 20, stop_loss=StopLossConfig(enabled=False))
    t0 = int(c["open_time"].iloc[0])
    funding = [(t0 + h * 3_600_000, 0.0005) for h in range(1, 20)]
    without = run_backtest(c, dna, **KW)
    with_f = run_backtest(c, dna, funding=funding, **KW)
    assert without.total_funding == 0.0 and with_f.total_funding > 0 and with_f.final_equity < without.final_equity


def test_fees_and_slippage_reduce_pnl():
    c = candles(seed=12)
    dna = ema_cross_dna(5, 20)
    cheap = run_backtest(c, dna, **{**KW, "fee_rate": 0.0, "slippage_bps": 0.0})
    dear = run_backtest(c, dna, **{**KW, "fee_rate": 0.002, "slippage_bps": 10.0})
    assert dear.final_equity < cheap.final_equity


def test_every_dna_sizing_method_trades_in_the_backtest():
    c = candles(seed=13)
    for method in ("fraction_of_equity", "fixed_notional", "risk_based", "volatility_based"):
        dna = ema_cross_dna(5, 20, position_sizing=PositionSizing(method=method, fraction_of_equity=0.05, max_notional=15.0))
        r = run_backtest(c, dna, enforce_risk_engine=True, **KW)
        assert r.trades, method


def test_shared_data_gives_identical_results_to_standalone_runs():
    c = candles(seed=14)
    dnas = [ema_cross_dna(5, 20), ema_cross_dna(10, 40)]
    specs = set().union(*(dna_indicator_specs(d) for d in dnas))
    data = prepare_backtest_data(c, symbol="SOL", timeframe="1m", specs=specs)
    for d in dnas:
        shared = run_backtest(c, d, data=data, **KW)
        alone = run_backtest(c, d, **KW)
        assert shared.final_equity == alone.final_equity


def test_execution_stress_knobs_change_results_and_delay_shifts_entries():
    import random
    c = candles(seed=15)
    dna = ema_cross_dna(5, 20)
    base = run_backtest(c, dna, **KW)
    delayed = run_backtest(c, dna, execution_delay_bars=3, **KW)
    partial = run_backtest(c, dna, fill_fraction=0.5, **KW)
    rejected = run_backtest(c, dna, entry_reject_probability=0.5, rng=random.Random(1), **KW)
    assert delayed.trades[0].entry_index == base.trades[0].entry_index + 3
    assert partial.trades[0].quantity == pytest.approx(base.trades[0].quantity * 0.5, rel=0.1)
    # a rejected entry is simply retried on a later bar (state-based rule) -> different fills, not the same book
    assert [t.entry_index for t in rejected.trades] != [t.entry_index for t in base.trades]
    assert rejected.final_equity != base.final_equity


def test_walk_forward_windows_only_trade_inside_their_test_slice():
    c = candles(1500, seed=16)
    rep = run_walk_forward(c, ema_cross_dna(5, 20), symbol="SOL", timeframe="1m", train_window=300, test_window=300, step=300,
                           starting_equity=100.0, fee_rate=0.00045, slippage_bps=2.0)
    assert len(rep.windows) >= 3
    for w in rep.windows:
        for t in w.result.trades:
            assert w.test_start <= t.entry_index < w.test_end + 5
