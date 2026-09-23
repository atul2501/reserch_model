"""RealityGapEngine: missed-trade attribution, the full Backtest->...->Live
chain report built on top of stage_metrics_service's existing pairwise
compute_reality_gap, and the richer cost/latency StageMetrics fields."""
from __future__ import annotations

import itertools
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from tests.helpers_agents import closed_position
from sqlalchemy import select

from app.backtesting.engine import BacktestResult, BacktestTrade
from app.backtesting.reality_gap_engine import compute_full_reality_gap_chain, persist_reality_gap_report
from app.backtesting.stage_metrics_service import (
    compute_live_stage_metrics,
    compute_missed_trade_stats,
    persist_backtest_metrics,
)
from app.models.agent import Agent
from app.models.decision import Decision
from app.models.enums import Bias, ExecutionVenue, OrderStatus, RiskDecision, Side, StrategyFamily, StrategyStage
from app.models.reality_gap import RealityGapReport
from app.models.stage_metrics import StageMetrics
from app.models.strategy import Strategy, StrategyVersion
from app.models.trading import Order, Trade
from app.schemas.strategy_dna import Condition, RuleSet, StrategyDNA


async def _seed_strategy_and_agent(db_session) -> tuple[uuid.UUID, Agent]:
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

    agent = Agent(
        identifier=f"GEN01-AG{uuid.uuid4().hex[:4]}",
        generation=1,
        strategy_version_id=version.id,
        starting_balance=100.0,
        balance=100.0,
        equity=100.0,
        peak_equity=100.0,
        day_start_equity=100.0,
        day_start_date=date.today(),
    )
    db_session.add(agent)
    await db_session.flush()
    return version.id, agent


_candle_counter = itertools.count(1)


def _decision(*, agent_id, strategy_version_id, risk_decision, risk_reasoning, order_id=None, trade_id=None, market_timestamp=None):
    return Decision(
        agent_id=agent_id,
        strategy_version_id=strategy_version_id,
        market_candle_open_time=next(_candle_counter),
        market_timestamp=market_timestamp or datetime.now(timezone.utc),
        market_context={},
        agent_signal=Bias.LONG,
        agent_signal_confidence=0.8,
        risk_decision=risk_decision,
        risk_reasoning=risk_reasoning,
        order_id=order_id,
        trade_id=trade_id,
    )


@pytest.mark.asyncio
async def test_compute_missed_trade_stats_distinguishes_skip_reject_and_unfilled(db_session):
    version_id, agent = await _seed_strategy_and_agent(db_session)
    now = datetime.now(timezone.utc)

    # 1. No-signal skip — must be excluded entirely (not an entry attempt).
    db_session.add(
        _decision(
            agent_id=agent.id, strategy_version_id=version_id,
            risk_decision=RiskDecision.REJECTED, risk_reasoning={"skipped": "no_entry_signal_or_position_open"},
        )
    )

    # 2. Real risk-engine rejection — a genuine missed trade.
    db_session.add(
        _decision(
            agent_id=agent.id, strategy_version_id=version_id,
            risk_decision=RiskDecision.REJECTED, risk_reasoning={"reasons": ["max_drawdown_exceeded"], "approved_notional": 0.0},
        )
    )

    # 3. Approved, order filled — a successful entry, contributes to latency.
    filled_order = Order(
        agent_id=agent.id, client_order_id=f"filled-{uuid.uuid4().hex}", symbol="SOL", side=Side.LONG,
        quantity=1.0, venue=ExecutionVenue.PAPER, status=OrderStatus.FILLED,
        filled_at=now + timedelta(seconds=2), latency_ms=150,
    )
    db_session.add(filled_order)
    await db_session.flush()
    db_session.add(
        _decision(
            agent_id=agent.id, strategy_version_id=version_id,
            risk_decision=RiskDecision.APPROVED, risk_reasoning={"reasons": [], "approved_notional": 10.0},
            order_id=filled_order.id, market_timestamp=now,
        )
    )

    # 4. Approved, order never filled — a missed trade despite passing risk.
    failed_order = Order(
        agent_id=agent.id, client_order_id=f"failed-{uuid.uuid4().hex}", symbol="SOL", side=Side.LONG,
        quantity=1.0, venue=ExecutionVenue.PAPER, status=OrderStatus.FAILED,
    )
    db_session.add(failed_order)
    await db_session.flush()
    db_session.add(
        _decision(
            agent_id=agent.id, strategy_version_id=version_id,
            risk_decision=RiskDecision.APPROVED, risk_reasoning={"reasons": [], "approved_notional": 10.0},
            order_id=failed_order.id,
        )
    )
    await db_session.commit()

    stats = await compute_missed_trade_stats(db_session, version_id)

    assert stats.total_entry_signals == 3  # the "skipped" decision is excluded
    assert stats.missed_trade_count == 2  # the risk-rejected one + the failed-order one
    assert stats.missed_trade_pct == pytest.approx(2 / 3)
    assert stats.avg_signal_to_fill_seconds == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_compute_full_reality_gap_chain_skips_absent_stages_without_raising(db_session):
    version_id, _ = await _seed_strategy_and_agent(db_session)
    now = datetime.now(timezone.utc)

    # Only BACKTEST and PAPER have metrics — WALK_FORWARD/OOS/SHADOW/etc.
    # were never reached by this strategy version.
    db_session.add(
        StageMetrics(
            strategy_version_id=version_id, stage=StrategyStage.BACKTEST,
            net_return_pct=0.20, max_drawdown_pct=0.05, win_rate=0.6, profit_factor=2.0,
            trade_count=50, computed_at=now - timedelta(days=1),
        )
    )
    db_session.add(
        StageMetrics(
            strategy_version_id=version_id, stage=StrategyStage.PAPER,
            net_return_pct=0.05, max_drawdown_pct=0.10, win_rate=0.5, profit_factor=1.2,
            trade_count=40, computed_at=now,
        )
    )
    await db_session.commit()

    report = await compute_full_reality_gap_chain(db_session, version_id)

    assert report.stages_present == ["BACKTEST", "PAPER"]
    assert len(report.transitions) == 1
    assert report.transitions[0]["from_stage"] == "BACKTEST"
    assert report.transitions[0]["to_stage"] == "PAPER"
    assert report.cumulative_gap is not None
    assert report.cumulative_gap["from_stage"] == "BACKTEST"
    assert report.cumulative_gap["to_stage"] == "PAPER"


@pytest.mark.asyncio
async def test_compute_full_reality_gap_chain_empty_when_no_metrics_exist(db_session):
    version_id, _ = await _seed_strategy_and_agent(db_session)

    report = await compute_full_reality_gap_chain(db_session, version_id)

    assert report.stages_present == []
    assert report.transitions == []
    assert report.cumulative_gap is None


@pytest.mark.asyncio
async def test_persist_reality_gap_report_never_overwrites(db_session):
    version_id, _ = await _seed_strategy_and_agent(db_session)

    report = await compute_full_reality_gap_chain(db_session, version_id)
    await persist_reality_gap_report(db_session, report)
    await db_session.commit()
    await persist_reality_gap_report(db_session, report)
    await db_session.commit()

    rows = (
        await db_session.execute(select(RealityGapReport).where(RealityGapReport.strategy_version_id == version_id))
    ).scalars().all()
    assert len(rows) == 2


def test_persist_backtest_metrics_populates_fee_and_slippage_fields():
    trade = BacktestTrade(
        side=Side.LONG, entry_index=0, exit_index=1, entry_price=100.0, exit_price=105.0,
        quantity=1.0, net_pnl=5.0, exit_reason="signal", fee=0.5, slippage_cost=0.2,
    )
    result = BacktestResult(equity_curve=[100.0, 105.0], trades=[trade], final_equity=105.0, starting_equity=100.0)

    row = persist_backtest_metrics(uuid.uuid4(), StrategyStage.BACKTEST, result)

    assert row.total_fees == pytest.approx(0.5)
    assert row.total_slippage_cost == pytest.approx(0.2)
    assert row.avg_trade_net_pnl == pytest.approx(5.0)


@pytest.mark.asyncio
async def test_compute_live_stage_metrics_populates_cost_and_latency_fields(db_session):
    version_id, agent = await _seed_strategy_and_agent(db_session)
    now = datetime.now(timezone.utc)

    filled_order = Order(
        agent_id=agent.id, client_order_id=f"o-{uuid.uuid4().hex}", symbol="SOL", side=Side.LONG,
        quantity=1.0, venue=ExecutionVenue.PAPER, status=OrderStatus.FILLED, latency_ms=200,
    )
    db_session.add(filled_order)
    db_session.add(
        Trade(
            agent_id=agent.id, position_id=closed_position(db_session, agent), symbol="SOL", side=Side.LONG, quantity=1.0,
            entry_price=100.0, exit_price=106.0, gross_pnl=6.0, fees=0.5, funding=0.1, slippage_cost=0.3,
            net_pnl=5.1, opened_at=now - timedelta(minutes=5), closed_at=now,
            holding_seconds=300, exit_reason="signal", stage=StrategyStage.PAPER,
        )
    )
    await db_session.commit()

    metrics = await compute_live_stage_metrics(db_session, strategy_version_id=version_id, stage=StrategyStage.PAPER)

    assert metrics.total_fees == pytest.approx(0.5)
    assert metrics.total_funding == pytest.approx(0.1)
    assert metrics.total_slippage_cost == pytest.approx(0.3)
    assert metrics.avg_trade_net_pnl == pytest.approx(5.1)
    assert metrics.avg_latency_ms == pytest.approx(200.0)
