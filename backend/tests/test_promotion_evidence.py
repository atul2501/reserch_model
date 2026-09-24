"""Champion/challenger promotion must rest on more than PnL (spec phases 25, 27, 29)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.evolution.champion import CandidateMetrics, PromotionCriteria, evaluate_promotion
from app.evolution.promotion_service import evaluate_and_promote
from app.models.agent import Agent
from app.models.enums import ChampionStatus, StrategyStage
from app.models.stage_metrics import StageMetrics
from app.models.strategy import Strategy, StrategyVersion
from tests.helpers_agents import add_promotion_evidence, make_agents
from tests.test_backtest_parity import ema_cross_dna

C = PromotionCriteria()


def good(**kw):
    d = dict(trade_count=150, oos_score=0.8, walk_forward_consistency=0.8, max_drawdown=0.05, profit_factor=2.0, fitness=0.5,
             adversarial_robustness=0.8, regime_classification="ROBUST", mean_correlation=0.3,
             reality_gap_return_degradation=0.1, paper_trade_count=150)
    d.update(kw)
    return CandidateMetrics(**d)


def test_a_fully_evidenced_candidate_is_promoted():
    assert evaluate_promotion(good(), None, C).promote


@pytest.mark.parametrize("override,needle", [
    (dict(oos_score=0.4), "oos_score"),
    (dict(walk_forward_consistency=0.2), "walk_forward"),
    (dict(max_drawdown=0.6), "max_drawdown"),
    (dict(profit_factor=1.0), "profit_factor"),
    (dict(trade_count=10), "trade_count"),
    (dict(adversarial_robustness=0.2), "adversarial_robustness"),
    (dict(mean_correlation=0.95), "mean_correlation"),
    (dict(reality_gap_return_degradation=0.8), "reality_gap"),
    (dict(paper_trade_count=5), "paper_trade_count"),
])
def test_each_gate_can_block_promotion_on_its_own(override, needle):
    d = evaluate_promotion(good(**override), None, C)
    assert not d.promote and any(needle in r for r in d.reasons)


@pytest.mark.parametrize("field", ["adversarial_robustness", "regime_classification", "reality_gap_return_degradation"])
def test_missing_evidence_blocks_promotion(field):
    d = evaluate_promotion(good(**{field: None}), None, C)
    assert not d.promote and any("missing_evidence" in r for r in d.reasons)


def test_high_pnl_alone_never_promotes():
    pnl_only = CandidateMetrics(trade_count=500, oos_score=None, walk_forward_consistency=None, max_drawdown=0.01, profit_factor=9.0, fitness=9.0)
    assert not evaluate_promotion(pnl_only, None, C).promote


def test_specialists_are_not_rejected_and_fragile_needs_a_clearer_oos_edge():
    assert evaluate_promotion(good(regime_classification="REGIME_SPECIALIST"), None, C).promote
    fragile_ok = evaluate_promotion(good(regime_classification="FRAGILE", oos_score=0.80), None, C)
    fragile_weak = evaluate_promotion(good(regime_classification="FRAGILE", oos_score=0.70), None, C)
    assert fragile_ok.promote and not fragile_weak.promote and any("required 0.75" in r for r in fragile_weak.reasons)
    assert not evaluate_promotion(good(regime_classification="UNSTABLE", oos_score=0.70), None, C).promote


def test_challenger_must_beat_the_champion_by_a_margin():
    champ = good(fitness=0.50)
    assert not evaluate_promotion(good(fitness=0.52), champ, C).promote
    assert evaluate_promotion(good(fitness=0.60), champ, C).promote


def test_criteria_come_from_settings():
    from app.core.config import get_settings
    s = get_settings()
    c = PromotionCriteria.from_settings(s)
    assert c.min_trade_count == s.champion_min_trade_count and c.min_oos_score == s.champion_min_oos_score
    assert c.max_reality_gap_return_degradation == s.reality_gap_max_acceptable_degradation_pct


async def _promo_setup(db, *, days=30):
    (agent,) = await make_agents(db, [ema_cross_dna(5, 20)])
    vid = agent.strategy_version_id
    version = await db.get(StrategyVersion, vid)
    version.stage_entered_at = datetime.now(timezone.utc) - timedelta(days=days)
    now = datetime.now(timezone.utc)
    db.add(StageMetrics(strategy_version_id=vid, stage=StrategyStage.PAPER, net_return_pct=0.28, max_drawdown_pct=0.05, win_rate=0.6,
                        profit_factor=2.0, trade_count=150, computed_at=now, observed_days=14.0))
    db.add(StageMetrics(strategy_version_id=vid, stage=StrategyStage.OUT_OF_SAMPLE, net_return_pct=0.1, max_drawdown_pct=0.05,
                        trade_count=40, oos_score=0.85, computed_at=now))
    db.add(StageMetrics(strategy_version_id=vid, stage=StrategyStage.WALK_FORWARD, net_return_pct=0.1, max_drawdown_pct=0.05,
                        trade_count=60, walk_forward_consistency=0.8, computed_at=now))
    await add_promotion_evidence(db, vid, backtest_return=0.30, with_oos=False)   # the OOS row above is the evidence
    await db.commit()
    return version


async def test_service_promotes_only_with_the_full_evidence_and_records_the_reasons(db_session):
    version = await _promo_setup(db_session)
    d = await evaluate_and_promote(db_session, version.id, stage=StrategyStage.PAPER)
    assert d.promote, d.reasons
    await db_session.refresh(version)
    assert version.champion_status == ChampionStatus.CHAMPION


async def test_service_reads_the_protected_oos_score_from_the_lockbox_stage(db_session):
    version = await _promo_setup(db_session)
    rows = (await db_session.execute(select(StageMetrics).where(StageMetrics.stage == StrategyStage.OUT_OF_SAMPLE))).scalars().all()
    rows[0].oos_score = 0.2
    await db_session.commit()
    d = await evaluate_and_promote(db_session, version.id, stage=StrategyStage.PAPER)
    assert not d.promote and any("oos_score" in r for r in d.reasons)


async def test_real_time_in_stage_gates_promotion(db_session):
    version = await _promo_setup(db_session, days=2)
    d = await evaluate_and_promote(db_session, version.id, stage=StrategyStage.PAPER)
    assert not d.promote and any("stage_track_record" in r for r in d.reasons)


async def test_child_is_compared_with_its_lineage_champion_not_with_itself(db_session):
    (parent_agent,) = await make_agents(db_session, [ema_cross_dna(5, 20)], generation=100)
    parent = await db_session.get(StrategyVersion, parent_agent.strategy_version_id)
    parent_strategy = await db_session.get(Strategy, parent.strategy_id)
    parent_strategy.lineage_id = parent_strategy.id
    parent.champion_status = ChampionStatus.CHAMPION
    now = datetime.now(timezone.utc)
    db_session.add(StageMetrics(strategy_version_id=parent.id, stage=StrategyStage.PAPER, net_return_pct=0.2, max_drawdown_pct=0.05,
                                profit_factor=2.0, trade_count=150, computed_at=now, observed_days=14.0))
    parent_agent.fitness = 0.9
    await db_session.commit()

    # a CHILD strategy in the same lineage (different Strategy row, as breeding creates)
    child_strategy = Strategy(code="S-CHILD", family=parent_strategy.family, name="child", lineage_id=parent_strategy.id)
    db_session.add(child_strategy)
    await db_session.flush()
    child = StrategyVersion(strategy_id=child_strategy.id, version=1, generation=101, dna=parent.dna,
                            parent_strategy_version_id=parent.id, stage=StrategyStage.PAPER,
                            stage_entered_at=now - timedelta(days=30))
    db_session.add(child)
    await db_session.flush()
    db_session.add(Agent(identifier="GEN101-AG0001", generation=101, strategy_version_id=child.id, starting_balance=100.0, balance=100.0,
                         equity=100.0, peak_equity=100.0, day_start_equity=100.0, day_start_date=now.date(), fitness=0.5))
    db_session.add_all([
        StageMetrics(strategy_version_id=child.id, stage=StrategyStage.PAPER, net_return_pct=0.28, max_drawdown_pct=0.05,
                     profit_factor=2.0, trade_count=150, computed_at=now, observed_days=14.0),
        StageMetrics(strategy_version_id=child.id, stage=StrategyStage.OUT_OF_SAMPLE, net_return_pct=0.1, max_drawdown_pct=0.05,
                     trade_count=40, oos_score=0.85, computed_at=now),
        StageMetrics(strategy_version_id=child.id, stage=StrategyStage.WALK_FORWARD, net_return_pct=0.1, max_drawdown_pct=0.05,
                     trade_count=60, walk_forward_consistency=0.8, computed_at=now),
    ])
    await add_promotion_evidence(db_session, child.id, backtest_return=0.30)
    await db_session.commit()

    d = await evaluate_and_promote(db_session, child.id, stage=StrategyStage.PAPER)
    # The lineage champion (fitness 0.9) is now the yardstick: 0.5 does not beat it by the margin.
    assert not d.promote and any("fitness improvement" in r for r in d.reasons)


async def test_promotion_freezes_an_immutable_snapshot_of_what_was_promoted(db_session):
    from app.models.strategy import AgentSnapshot
    version = await _promo_setup(db_session)
    d = await evaluate_and_promote(db_session, version.id, stage=StrategyStage.PAPER)
    assert d.promote
    await db_session.commit()
    snaps = (await db_session.execute(select(AgentSnapshot).where(AgentSnapshot.strategy_version_id == version.id))).scalars().all()
    assert len(snaps) == 1 and snaps[0].strategy_dna == version.dna and snaps[0].schema_version
