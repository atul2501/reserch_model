"""Event-driven backtester: no look-ahead, sane trade accounting (spec 22/45)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.backtesting.engine import run_backtest
from app.backtesting.splits import chronological_split
from app.backtesting.walk_forward import run_walk_forward
from app.models.enums import StrategyFamily
from app.schemas.strategy_dna import Condition, PositionSizing, RiskProfile, RuleSet, StrategyDNA


def _trending_candles(n: int, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    price = 100.0
    rows = []
    for i in range(n):
        price += 0.05 + rng.normal(0, 0.15)
        open_ = price
        close = price + rng.normal(0, 0.1)
        high = max(open_, close) + abs(rng.normal(0, 0.05))
        low = min(open_, close) - abs(rng.normal(0, 0.05))
        volume = abs(rng.normal(1000, 50))
        rows.append({"open_time": i * 60_000, "open": open_, "high": high, "low": low, "close": close, "volume": volume})
        price = close
    return pd.DataFrame(rows)


def _trend_dna() -> StrategyDNA:
    return StrategyDNA(
        strategy_family=StrategyFamily.TREND_FOLLOWING,
        indicators=[{"name": "ema", "params": {"period": 12}}],
        entry_rules=RuleSet(conditions=[Condition(feature="trend_strength", operator="gt", value=0)]),
        exit_rules=RuleSet(conditions=[Condition(feature="trend_strength", operator="lt", value=-0.001)]),
    )


def test_backtest_runs_and_tracks_equity():
    candles = _trending_candles(400)
    result = run_backtest(
        candles, _trend_dna(), symbol="SOL", timeframe="1m", starting_equity=100.0, fee_rate=0.00045, slippage_bps=2
    )
    assert len(result.equity_curve) > 0
    assert result.starting_equity == 100.0
    assert result.max_drawdown_pct >= 0.0


def test_backtest_fees_reduce_equity_vs_zero_cost():
    candles = _trending_candles(400)
    with_fees = run_backtest(
        candles, _trend_dna(), symbol="SOL", timeframe="1m", starting_equity=100.0, fee_rate=0.01, slippage_bps=50
    )
    no_fees = run_backtest(
        candles, _trend_dna(), symbol="SOL", timeframe="1m", starting_equity=100.0, fee_rate=0.0, slippage_bps=0
    )
    if with_fees.trades and no_fees.trades:
        assert with_fees.final_equity <= no_fees.final_equity


def test_entries_fill_at_next_bar_open_not_signal_bar_close():
    """Regression guard against look-ahead: a fill price equal to the
    signal bar's close (rather than the next bar's open) would indicate the
    backtester executed before the bar it decided on had actually closed."""
    candles = _trending_candles(400)
    result = run_backtest(
        candles, _trend_dna(), symbol="SOL", timeframe="1m", starting_equity=100.0, fee_rate=0.0, slippage_bps=0
    )
    for trade in result.trades:
        signal_bar_close = candles["close"].iloc[trade.entry_index - 1]
        assert trade.entry_price != signal_bar_close


def test_chronological_split_never_shuffles():
    candles = _trending_candles(1000)
    split = chronological_split(candles, train_fraction=0.6, validation_fraction=0.2)
    assert split.train["open_time"].max() < split.validation["open_time"].min()
    assert split.validation["open_time"].max() < split.final_test["open_time"].min()


def test_backtest_trades_carry_fee_slippage_and_regime():
    candles = _trending_candles(400)
    result = run_backtest(
        candles, _trend_dna(), symbol="SOL", timeframe="1m", starting_equity=100.0, fee_rate=0.001, slippage_bps=50
    )
    assert result.trades, "expected at least one trade for this to be a meaningful test"
    for trade in result.trades:
        assert trade.fee > 0.0
        assert trade.slippage_cost > 0.0
        assert trade.entry_regime is not None
        assert trade.exit_regime is not None


def test_enforce_risk_engine_caps_notional_via_real_risk_check():
    """A DNA proposing far more leverage than the global risk limits allow
    must come out smaller when enforce_risk_engine=True — proving entries
    are routed through the real check_trade, not bypassing it (adversarial
    testing must never bypass the Risk Engine)."""
    candles = _trending_candles(400)
    high_leverage_dna = StrategyDNA(
        strategy_family=StrategyFamily.TREND_FOLLOWING,
        indicators=[{"name": "ema", "params": {"period": 12}}],
        entry_rules=RuleSet(conditions=[Condition(feature="trend_strength", operator="gt", value=0)]),
        exit_rules=RuleSet(conditions=[Condition(feature="trend_strength", operator="lt", value=-0.001)]),
        risk_profile=RiskProfile(max_leverage=20.0, max_position_fraction=1.0),
        position_sizing=PositionSizing(fraction_of_equity=1.0),
        leverage_limit=20.0,
    )

    unenforced = run_backtest(
        candles, high_leverage_dna, symbol="SOL", timeframe="1m", starting_equity=100.0, fee_rate=0.0, slippage_bps=0
    )
    enforced = run_backtest(
        candles, high_leverage_dna, symbol="SOL", timeframe="1m", starting_equity=100.0, fee_rate=0.0, slippage_bps=0,
        enforce_risk_engine=True, global_max_leverage=5.0, global_max_position_size=0.5,
    )

    assert unenforced.trades, "expected the unenforced run to open at least one trade"
    assert enforced.trades, "risk-gating should reduce size, not eliminate all entries"
    assert enforced.trades[0].quantity < unenforced.trades[0].quantity


def test_walk_forward_reports_every_window():
    candles = _trending_candles(600)
    report = run_walk_forward(
        candles,
        _trend_dna(),
        symbol="SOL",
        timeframe="1m",
        train_window=250,
        test_window=50,
        step=50,
        starting_equity=100.0,
        fee_rate=0.00045,
        slippage_bps=2,
    )
    assert len(report.windows) > 1
    assert 0.0 <= report.consistency_score <= 1.0
