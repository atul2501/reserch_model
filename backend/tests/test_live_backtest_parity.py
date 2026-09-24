"""LIVE (paper, through the real worker cycle) vs BACKTEST parity (spec phases 5, 16).

The same DNA on the same candles must produce the same trades: same entry/exit bars, prices, quantities, exit reasons,
fees, funding and PnL. Live decides on the closed bar and fills at the NEXT open; the backtest does exactly that."""
from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import select

from app.backtesting.engine import run_backtest
from app.core.config import get_settings
from app.execution.paper_adapter import PaperExecutionAdapter
from app.market.feature_engine import MIN_CANDLES_REQUIRED
from app.market.market_data_service import MarketDataService
from app.models.enums import StrategyFamily
from app.models.trading import Trade
from app.schemas.strategy_dna import (
    Condition, CooldownConfig, PositionSizing, RiskProfile, RuleSet, StopLossConfig, StrategyDNA, TakeProfitConfig,
    TrailingStopConfig,
)
from app.worker import cycle as cycle_mod
from tests.helpers_agents import make_agents
from tests.helpers_market import INTERVAL, T0, FakeHyperliquid, clock_after_bar

N = 400


def static_dna(**kw) -> StrategyDNA:
    """Only STATIC features (rsi_14): live and backtest compute them on the identical trailing window."""
    base = dict(
        strategy_family=StrategyFamily.MOMENTUM,
        indicators=[{"name": "rsi", "params": {"period": 14}}],
        entry_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="gt", value=58)]),
        exit_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="lt", value=45)]),
        direction_mode="long_only",
        risk_profile=RiskProfile(max_leverage=2.0, max_position_fraction=0.5), leverage_limit=2.0,
        position_sizing=PositionSizing(fraction_of_equity=0.2),
        stop_loss=StopLossConfig(method="atr_multiple", value=2.0),
        take_profit=TakeProfitConfig(method="risk_reward_multiple", value=2.0),
    )
    base.update(kw)
    return StrategyDNA(**base)


SCENARIOS = {
    "stops_and_take_profit": static_dna(),
    "cooldown_and_daily_cap": static_dna(cooldown=CooldownConfig(bars_after_loss=6, bars_after_win=3), max_trades_per_day=4),
    "trailing_stop": static_dna(take_profit=TakeProfitConfig(enabled=False),
                                trailing_stop=TrailingStopConfig(enabled=True, activation_pct=0.2, trail_pct=0.4)),
    "short_only": static_dna(direction_mode="short_only",
                             entry_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="lt", value=42)]),
                             exit_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="gt", value=55)])),
}


@pytest.fixture
def deterministic(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "council_enabled", False)
    monkeypatch.setattr(s, "paper_latency_ms", 0)
    monkeypatch.setattr(s, "paper_latency_jitter_ms", 0)
    for name in ("paper_reject_probability", "paper_partial_fill_probability", "paper_latency_drift_bps_per_sec"):
        monkeypatch.setattr(s, name, 0.0)
    monkeypatch.setattr(s, "paper_min_order_notional", 0.0)
    assert s.paper_fill_timing == "next_open"
    return s


def _frame(fake: FakeHyperliquid) -> pd.DataFrame:
    return pd.DataFrame([{
        "open_time": c["t"], "open": float(c["o"]), "high": float(c["h"]), "low": float(c["l"]),
        "close": float(c["c"]), "volume": float(c["v"]),
    } for c in fake.candles])


async def _run_live(db, fake, dna):
    await make_agents(db, [dna], generation=1, balance=100.0)
    market = MarketDataService(fake, clock_ms=lambda: 0)
    eng = PaperExecutionAdapter()
    for i in range(MIN_CANDLES_REQUIRED, N):
        market._clock_ms = lambda i=i: clock_after_bar(i)          # bar i has just closed
        out = await cycle_mod.run_pending_cycles(db, market, None, execution_engine=eng)
        assert all(o.status == "COMPLETED" for o in out)
    return (await db.execute(select(Trade).order_by(Trade.closed_at))).scalars().all()


def _funding(fake):
    return [(int(f["time"]), float(f["fundingRate"])) for f in fake.funding]


@pytest.mark.parametrize("name", list(SCENARIOS))
async def test_same_dna_same_candles_same_trades(db_session, deterministic, name):
    s = deterministic
    dna = SCENARIOS[name]
    fake = FakeHyperliquid(n_candles=N)
    live = await _run_live(db_session, fake, dna)

    bt = run_backtest(
        _frame(fake), dna, symbol="SOL", timeframe="1m", starting_equity=100.0, fee_rate=s.paper_fee_rate,
        slippage_bps=s.paper_slippage_bps, enforce_risk_engine=True, global_max_leverage=s.max_leverage,
        global_max_position_size=s.max_position_size, global_max_drawdown=s.max_drawdown,
        global_max_daily_loss=s.max_daily_loss, funding=_funding(fake), start_index=MIN_CANDLES_REQUIRED,
    )
    bt_trades = [t for t in bt.trades if t.exit_reason != "end_of_data"]      # live keeps its last position open

    assert len(live) >= 2, f"scenario {name} must actually trade to mean anything (got {len(live)})"
    assert len(live) == len(bt_trades), [(t.entry_price, t.exit_reason) for t in live]
    for lt, bt_ in zip(live, bt_trades):
        assert lt.side == bt_.side
        assert lt.entry_price == pytest.approx(bt_.entry_price, rel=1e-9)
        assert lt.exit_price == pytest.approx(bt_.exit_price, rel=1e-9)
        assert lt.quantity == pytest.approx(bt_.quantity, rel=1e-9)
        assert lt.exit_reason.split("|")[0] == bt_.exit_reason or (lt.exit_reason, bt_.exit_reason) == ("exit_rules", "signal")
        assert lt.fees == pytest.approx(bt_.fee, rel=1e-9)
        assert lt.funding == pytest.approx(bt_.funding, abs=1e-9)
        assert lt.net_pnl == pytest.approx(bt_.net_pnl, rel=1e-7, abs=1e-9)


async def test_parity_scenarios_exercise_more_than_one_exit_reason(db_session, deterministic):
    """Guard against a vacuous parity suite: across the scenarios stops, signal exits and trailing all occur."""
    reasons: set[str] = set()
    for name in ("stops_and_take_profit", "trailing_stop"):
        fake = FakeHyperliquid(n_candles=N)
        s = deterministic
        bt = run_backtest(_frame(fake), SCENARIOS[name], symbol="SOL", timeframe="1m", starting_equity=100.0,
                          fee_rate=s.paper_fee_rate, slippage_bps=s.paper_slippage_bps)
        reasons |= {t.exit_reason for t in bt.trades}
    assert len(reasons) >= 2
