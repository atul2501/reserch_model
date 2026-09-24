"""Reality gap (spec phase 20): stages are compared per unit of time, and only when each was observed long enough."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.backtesting.engine import run_backtest
from app.backtesting.stage_metrics_service import (
    REALITY_GAP_METRICS, comparability, compute_live_stage_metrics, compute_reality_gap, persist_backtest_metrics,
)
from app.core.config import get_settings
from app.evolution.promotion_service import evaluate_and_promote
from app.models.enums import AgentStatus, Side, StrategyStage
from app.models.stage_metrics import StageMetrics
from app.models.trading import Trade
from tests.helpers_agents import add_promotion_evidence, closed_position, make_agents, make_dna
from tests.test_backtest_parity import KW, candles, ema_cross_dna
from tests.test_champion_challenger_service import _seed_version


def row(stage, *, days, trades=50, ret=0.28, fees=5.0, slip=2.0, funding=1.0, avg=0.1, vid=None):
    return StageMetrics(strategy_version_id=vid or uuid.uuid4(), stage=stage, net_return_pct=ret, max_drawdown_pct=0.05,
                        win_rate=0.6, profit_factor=1.8, trade_count=trades, total_fees=fees, total_slippage_cost=slip,
                        total_funding=funding, avg_trade_net_pnl=avg, observed_days=days, computed_at=datetime.now(timezone.utc))


def test_a_multi_day_backtest_vs_one_day_of_paper_is_not_comparable():
    ok, reasons = comparability(row(StrategyStage.BACKTEST, days=14), row(StrategyStage.PAPER, days=1.0))
    assert not ok and any("to_stage_observed_1.00d" in r for r in reasons)


def test_too_few_trades_or_an_unknown_window_is_not_comparable():
    ok, reasons = comparability(row(StrategyStage.BACKTEST, days=14), row(StrategyStage.PAPER, days=10, trades=3))
    assert not ok and any("trade_count_3" in r for r in reasons)
    legacy = row(StrategyStage.PAPER, days=None)
    ok, reasons = comparability(row(StrategyStage.BACKTEST, days=14), legacy)
    assert not ok and "to_stage_observation_window_unknown" in reasons


def test_enough_time_and_trades_on_both_sides_is_comparable():
    ok, reasons = comparability(row(StrategyStage.BACKTEST, days=14), row(StrategyStage.PAPER, days=5))
    assert ok and reasons == []


async def test_reality_gap_reports_per_day_rates_so_different_lengths_compare_fairly(db_session):
    vid = (await _seed_version(db_session)).id
    db_session.add(row(StrategyStage.BACKTEST, days=14, ret=0.28, trades=140, fees=14.0, slip=7.0, funding=2.8, avg=0.2, vid=vid))
    db_session.add(row(StrategyStage.PAPER, days=7, ret=0.14, trades=70, fees=7.0, slip=3.5, funding=1.4, avg=0.2, vid=vid))
    await db_session.commit()
    gap = await compute_reality_gap(db_session, vid, StrategyStage.BACKTEST, StrategyStage.PAPER)
    assert gap["comparable"] and gap["from_observed_days"] == 14 and gap["to_observed_days"] == 7
    assert gap["net_return_pct"]["pct_change"] == pytest.approx(-0.5)                # raw totals differ 2x ...
    assert gap["net_return_per_day"]["pct_change"] == pytest.approx(0.0)              # ... per day they are identical
    assert gap["trade_count_per_day"]["pct_change"] == pytest.approx(0.0)
    assert gap["fees_per_trade"]["from"] == pytest.approx(0.1) and gap["fees_per_trade"]["pct_change"] == pytest.approx(0.0)
    assert gap["funding_per_day"]["pct_change"] == pytest.approx(0.0)
    assert gap["trade_count"]["from"] == 140 and gap["trade_count"]["to"] == 70
    assert gap["net_pnl"]["from"] == pytest.approx(28.0)
    assert {"trade_count", "net_pnl", "net_return_per_day", "trade_count_per_day", "fees_per_trade"} <= set(REALITY_GAP_METRICS)


async def test_short_observation_is_flagged_but_the_numbers_are_still_reported(db_session):
    vid = (await _seed_version(db_session)).id
    db_session.add(row(StrategyStage.BACKTEST, days=14, vid=vid))
    db_session.add(row(StrategyStage.PAPER, days=0.5, vid=vid))
    await db_session.commit()
    gap = await compute_reality_gap(db_session, vid, StrategyStage.BACKTEST, StrategyStage.PAPER)
    assert gap["comparable"] is False and gap["not_comparable_reasons"] and gap["net_return_pct"]["to"] is not None


async def test_promotion_treats_an_unreliable_reality_gap_as_missing_evidence(db_session):
    async def setup(paper_days):
        version = await _seed_version(db_session, stage=StrategyStage.PAPER)
        await add_promotion_evidence(db_session, version.id)
        db_session.add(StageMetrics(strategy_version_id=version.id, stage=StrategyStage.PAPER, net_return_pct=0.28,
                                    max_drawdown_pct=0.05, win_rate=0.7, profit_factor=2.0, trade_count=150, oos_score=0.8,
                                    walk_forward_consistency=0.8, observed_days=paper_days,
                                    computed_at=datetime.now(timezone.utc) + timedelta(seconds=5)))
        db_session.add(StageMetrics(strategy_version_id=version.id, stage=StrategyStage.WALK_FORWARD, net_return_pct=0.1,
                                    max_drawdown_pct=0.05, trade_count=60, walk_forward_consistency=0.8,
                                    computed_at=datetime.now(timezone.utc)))
        await db_session.commit()
        return version

    short = await setup(paper_days=0.5)
    d = await evaluate_and_promote(db_session, short.id, stage=StrategyStage.PAPER)
    assert not d.promote and any("reality gap" in r for r in d.reasons)
    long_ = await setup(paper_days=14)
    d = await evaluate_and_promote(db_session, long_.id, stage=StrategyStage.PAPER)
    assert d.promote, d.reasons


def test_backtest_stage_rows_carry_their_observation_window():
    c = candles(1500, seed=4)
    r = run_backtest(c, ema_cross_dna(5, 20), **KW)
    m = persist_backtest_metrics(uuid.uuid4(), StrategyStage.BACKTEST, r)
    assert m.observed_days == pytest.approx((1500 - 210) / 1440, rel=0.01)           # bars actually simulated, in days
    assert m.period_end_ms > m.period_start_ms and m.bar_count == r.bars_simulated


# --- live-stage metrics describe THAT stage, not the agent's lifetime ---------------------------------------------------


async def _live(db_session, pnls, *, stage=StrategyStage.PAPER, bad_debt=0.0, equity=999.0, qty=1.0):
    (agent,) = await make_agents(db_session, [make_dna()], stage=stage)
    agent.equity = equity                     # lifetime equity is IRRELEVANT to a stage's return
    agent.created_at = datetime.now(timezone.utc) - timedelta(days=4)
    base = datetime.now(timezone.utc) - timedelta(days=3)
    for i, p in enumerate(pnls):
        db_session.add(Trade(agent_id=agent.id, position_id=closed_position(db_session, agent), symbol="SOL", side=Side.LONG,
                             quantity=qty, entry_price=100, exit_price=100 + p / qty, gross_pnl=p, fees=0.0, net_pnl=p,
                             bad_debt=bad_debt if i == len(pnls) - 1 else 0.0, opened_at=base + timedelta(hours=i),
                             closed_at=base + timedelta(hours=i, minutes=5), holding_seconds=300, exit_reason="signal", stage=stage))
    await db_session.commit()
    return agent


async def test_live_stage_return_and_drawdown_come_from_the_stage_trades(db_session):
    agent = await _live(db_session, [10.0, -30.0, 5.0])
    m = await compute_live_stage_metrics(db_session, strategy_version_id=agent.strategy_version_id, stage=StrategyStage.PAPER)
    assert m.net_return_pct == pytest.approx(-0.15)                                   # (10 - 30 + 5) / 100, not equity 999
    assert m.max_drawdown_pct == pytest.approx(30.0 / 110.0)                          # 110 -> 80 from the trade curve
    assert m.trade_count == 3 and m.observed_days == pytest.approx(4.0, abs=0.01)
    assert m.period_start_ms < m.period_end_ms


async def test_live_stage_return_adds_bad_debt_back_so_it_cannot_exceed_minus_100_percent(db_session):
    agent = await _live(db_session, [-150.0], bad_debt=50.0, qty=1.6)                 # lost 150 on a $100 account: 50 was bad debt
    m = await compute_live_stage_metrics(db_session, strategy_version_id=agent.strategy_version_id, stage=StrategyStage.PAPER)
    assert m.net_return_pct == pytest.approx(-1.0)


async def test_stages_do_not_leak_into_each_other(db_session):
    agent = await _live(db_session, [10.0, 10.0], stage=StrategyStage.PAPER)
    shadow = await compute_live_stage_metrics(db_session, strategy_version_id=agent.strategy_version_id, stage=StrategyStage.SHADOW)
    paper = await compute_live_stage_metrics(db_session, strategy_version_id=agent.strategy_version_id, stage=StrategyStage.PAPER)
    assert paper.trade_count == 2 and paper.net_return_pct == pytest.approx(0.2)
    assert shadow.trade_count == 0 or shadow.net_return_pct != paper.net_return_pct
