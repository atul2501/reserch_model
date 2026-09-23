"""RegimeValidationEngine: per-regime breakdown from backtest and live
trade history, and the ROBUST/REGIME_SPECIALIST/FRAGILE/UNSTABLE
classification (no precedent for this existed anywhere in the codebase
before)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from tests.helpers_agents import closed_position
from sqlalchemy import select

from app.api.routes.trades import get_regime_performance
from app.backtesting.engine import BacktestResult, BacktestTrade
from app.backtesting.regime_validation_engine import (
    FRAGILE,
    REGIME_SPECIALIST,
    ROBUST,
    UNSTABLE,
    RegimeStats,
    classify_robustness,
    compute_regime_breakdown_backtest,
    compute_regime_breakdown_live,
    run_and_persist_regime_validation,
)
from app.models.agent import Agent
from app.models.enums import MarketRegime, Side, StrategyFamily
from app.models.market import MarketRegimeRecord
from app.models.regime_validation import RegimeValidationReport
from app.models.strategy import Strategy, StrategyVersion
from app.models.trading import Trade
from app.schemas.strategy_dna import Condition, RuleSet, StrategyDNA


def _bt_trade(net_pnl: float, exit_regime: str) -> BacktestTrade:
    return BacktestTrade(
        side=Side.LONG, entry_index=0, exit_index=1, entry_price=100.0, exit_price=100.0 + net_pnl,
        quantity=1.0, net_pnl=net_pnl, exit_reason="signal", exit_regime=exit_regime,
    )


def test_compute_regime_breakdown_backtest_groups_by_exit_regime():
    result = BacktestResult(
        equity_curve=[100.0, 105.0, 103.0, 108.0],
        trades=[
            _bt_trade(5.0, "TREND_UP"),
            _bt_trade(-2.0, "TREND_UP"),
            _bt_trade(5.0, "RANGE"),
        ],
        final_equity=108.0,
        starting_equity=100.0,
    )

    breakdown = compute_regime_breakdown_backtest(result)

    assert set(breakdown.keys()) == {"TREND_UP", "RANGE"}
    assert breakdown["TREND_UP"].trade_count == 2
    assert breakdown["TREND_UP"].pnl == pytest.approx(3.0)
    assert breakdown["RANGE"].trade_count == 1
    assert breakdown["RANGE"].pnl == pytest.approx(5.0)
    assert breakdown["RANGE"].expectancy == pytest.approx(5.0)


def _stats(*, trade_count: int, pnl: float) -> RegimeStats:
    return RegimeStats(
        trade_count=trade_count, pnl=pnl, roi=pnl / 100.0, profit_factor=None,
        win_rate=None, max_drawdown_pct=0.0, expectancy=pnl / trade_count if trade_count else None,
    )


def test_classify_robustness_robust_when_broadly_positive():
    per_regime = {
        "TREND_UP": _stats(trade_count=20, pnl=10.0),
        "TREND_DOWN": _stats(trade_count=20, pnl=8.0),
        "RANGE": _stats(trade_count=20, pnl=5.0),
        "HIGH_VOLATILITY": _stats(trade_count=20, pnl=6.0),
    }
    classification, reasons = classify_robustness(per_regime)
    assert classification == ROBUST
    assert reasons


def test_classify_robustness_regime_specialist_when_concentrated_but_not_broadly_losing():
    per_regime = {
        "TREND_UP": _stats(trade_count=20, pnl=50.0),   # dominant, strongly profitable
        "TREND_DOWN": _stats(trade_count=20, pnl=-5.0),  # one weak/losing regime — not enough to be FRAGILE
        "RANGE": _stats(trade_count=20, pnl=2.0),        # secondary, mildly profitable
    }
    # Only 2/3 regimes positive -> fails ROBUST's positive-regime-pct bar,
    # but the top two regimes still account for the large majority of PnL
    # and only 1/3 of tested regimes are negative -> REGIME_SPECIALIST, per
    # the user's own example (narrow-but-real edge, not broadly losing).
    classification, reasons = classify_robustness(per_regime)
    assert classification == REGIME_SPECIALIST
    assert reasons


def test_classify_robustness_fragile_when_profitable_in_isolation_but_losing_elsewhere():
    per_regime = {
        "TREND_UP": _stats(trade_count=20, pnl=5.0),
        "TREND_DOWN": _stats(trade_count=20, pnl=-8.0),
        "RANGE": _stats(trade_count=20, pnl=-6.0),
    }
    classification, reasons = classify_robustness(per_regime)
    assert classification == FRAGILE
    assert reasons


def test_classify_robustness_unstable_when_insufficient_regime_coverage():
    per_regime = {
        "TREND_UP": _stats(trade_count=20, pnl=5.0),
        "RANGE": _stats(trade_count=3, pnl=1.0),  # below min_trades_per_regime
    }
    classification, reasons = classify_robustness(per_regime, min_trades_per_regime=10)
    assert classification == UNSTABLE
    assert reasons


async def _seed_strategy_and_agent(db_session, *, starting_balance: float = 100.0) -> tuple[uuid.UUID, Agent]:
    code = f"STRAT-TEST-{uuid.uuid4().hex[:8]}"
    strategy = Strategy(code=code, family=StrategyFamily.MOMENTUM, name=code)
    db_session.add(strategy)
    await db_session.flush()
    dna = StrategyDNA(
        strategy_family=StrategyFamily.MOMENTUM,
        indicators=[{"name": "rsi", "params": {"period": 14}}],
        entry_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="gt", value=60)]),
        exit_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="lt", value=40)]),
    )
    version = StrategyVersion(strategy_id=strategy.id, version=1, generation=1, dna=dna.model_dump(mode="json"))
    db_session.add(version)
    await db_session.flush()

    from datetime import date
    agent = Agent(
        identifier=f"GEN01-AG{uuid.uuid4().hex[:4]}",
        generation=1,
        strategy_version_id=version.id,
        starting_balance=starting_balance,
        balance=starting_balance,
        equity=starting_balance,
        peak_equity=starting_balance,
        day_start_equity=starting_balance,
        day_start_date=date.today(),
    )
    db_session.add(agent)
    await db_session.flush()
    return version.id, agent


@pytest.mark.asyncio
async def test_compute_regime_breakdown_live_agrees_with_the_by_regime_route(db_session):
    """Regression guard for the shared regime_lookup.py extraction: the
    per-strategy live breakdown and the existing aggregate /by-regime route
    must attribute the same trades to the same regimes."""
    version_id, agent = await _seed_strategy_and_agent(db_session)

    now = datetime.now(timezone.utc)
    base_ms = int((now - timedelta(hours=2)).timestamp() * 1000)
    db_session.add_all([
        MarketRegimeRecord(
            symbol="SOL", timeframe="1m", candle_open_time=base_ms, regime=MarketRegime.TREND_UP, confidence=0.8
        ),
        MarketRegimeRecord(
            symbol="SOL", timeframe="1m", candle_open_time=base_ms + 3_600_000, regime=MarketRegime.RANGE, confidence=0.7
        ),
    ])

    trade_1_closed = now - timedelta(hours=1, minutes=30)  # after TREND_UP record, before RANGE record
    trade_2_closed = now - timedelta(minutes=10)  # after RANGE record
    db_session.add_all([
        Trade(
            agent_id=agent.id, position_id=closed_position(db_session, agent), symbol="SOL", side=Side.LONG, quantity=1.0,
            entry_price=100.0, exit_price=105.0, gross_pnl=5.0, fees=0.0, net_pnl=5.0,
            opened_at=trade_1_closed - timedelta(minutes=5), closed_at=trade_1_closed,
            holding_seconds=300, exit_reason="signal",
        ),
        Trade(
            agent_id=agent.id, position_id=closed_position(db_session, agent), symbol="SOL", side=Side.SHORT, quantity=1.0,
            entry_price=100.0, exit_price=98.0, gross_pnl=2.0, fees=0.0, net_pnl=2.0,
            opened_at=trade_2_closed - timedelta(minutes=5), closed_at=trade_2_closed,
            holding_seconds=300, exit_reason="signal",
        ),
    ])
    await db_session.commit()

    route_results = await get_regime_performance(db_session)
    route_by_regime = {r.regime: r.trade_count for r in route_results}

    live_breakdown = await compute_regime_breakdown_live(db_session, version_id)
    live_by_regime = {regime: stats.trade_count for regime, stats in live_breakdown.items()}

    assert route_by_regime == live_by_regime == {"TREND_UP": 1, "RANGE": 1}


@pytest.mark.asyncio
async def test_run_and_persist_regime_validation_from_backtest(db_session):
    version_id, _ = await _seed_strategy_and_agent(db_session)
    result = BacktestResult(
        equity_curve=[100.0, 110.0, 118.0],
        trades=[_bt_trade(10.0, "TREND_UP"), _bt_trade(8.0, "TREND_UP")],
        final_equity=118.0,
        starting_equity=100.0,
    )

    report = await run_and_persist_regime_validation(
        db_session, version_id, backtest_result=result, min_trades_per_regime=1
    )
    await db_session.commit()

    fetched = (
        await db_session.execute(
            select(RegimeValidationReport).where(RegimeValidationReport.strategy_version_id == version_id)
        )
    ).scalar_one()
    assert fetched.id == report.id
    assert fetched.classification in {ROBUST, REGIME_SPECIALIST, FRAGILE, UNSTABLE}
    assert "TREND_UP" in fetched.per_regime
    assert fetched.per_regime["TREND_UP"]["trade_count"] == 2
