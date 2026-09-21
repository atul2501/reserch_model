"""Champion/challenger promotion wiring: evaluate_promotion actually gets
called against persisted stage metrics and updates champion_status
(spec section 28)."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.evolution.promotion_service import MIN_STAGE_DAYS, evaluate_and_promote
from app.models.agent import Agent
from app.models.enums import ChampionStatus, StrategyFamily, StrategyStage
from app.models.stage_metrics import StageMetrics
from app.models.strategy import Strategy, StrategyVersion
from app.schemas.strategy_dna import Condition, RuleSet, StrategyDNA


def _agent_with_fitness(strategy_version_id, fitness: float, identifier: str) -> Agent:
    return Agent(
        identifier=identifier,
        generation=1,
        strategy_version_id=strategy_version_id,
        starting_balance=100.0,
        balance=100.0,
        equity=100.0,
        peak_equity=100.0,
        day_start_equity=100.0,
        day_start_date=date.today(),
        fitness=fitness,
    )


async def _seed_version(db_session, *, created_at: datetime, champion_status=None, strategy_id=None) -> StrategyVersion:
    if strategy_id is None:
        code = f"STRAT-TEST-{uuid.uuid4().hex[:8]}"
        strategy = Strategy(code=code, family=StrategyFamily.MOMENTUM, name=code)
        db_session.add(strategy)
        await db_session.flush()
        strategy_id = strategy.id

    dna = StrategyDNA(
        strategy_family=StrategyFamily.MOMENTUM,
        indicators=[{"name": "rsi", "params": {"period": 14}}],
        entry_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="gt", value=60)]),
        exit_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="lt", value=40)]),
    )
    existing_versions = (
        await db_session.execute(select(StrategyVersion).where(StrategyVersion.strategy_id == strategy_id))
    ).scalars().all()
    version = StrategyVersion(
        strategy_id=strategy_id,
        version=len(existing_versions) + 1,
        generation=1,
        dna=dna.model_dump(mode="json"),
        champion_status=champion_status,
    )
    db_session.add(version)
    await db_session.flush()
    version.created_at = created_at  # override TimestampMixin's default for track-record testing
    await db_session.commit()
    return version, strategy_id


def _passing_metrics(strategy_version_id, computed_at) -> StageMetrics:
    return StageMetrics(
        strategy_version_id=strategy_version_id,
        stage=StrategyStage.PAPER,
        net_return_pct=0.30,
        max_drawdown_pct=0.05,
        win_rate=0.7,
        profit_factor=2.0,
        trade_count=150,
        oos_score=0.8,
        walk_forward_consistency=0.8,
        computed_at=computed_at,
    )


@pytest.mark.asyncio
async def test_no_promotion_without_stage_metrics(db_session):
    now = datetime.now(timezone.utc)
    version, _ = await _seed_version(db_session, created_at=now - timedelta(days=30))

    decision = await evaluate_and_promote(db_session, version.id, stage=StrategyStage.PAPER)

    assert decision.promote is False
    assert "no_stage_metrics_recorded" in decision.reasons


@pytest.mark.asyncio
async def test_no_promotion_under_minimum_track_record(db_session):
    now = datetime.now(timezone.utc)
    created_at = now - timedelta(days=MIN_STAGE_DAYS - 1)
    version, _ = await _seed_version(db_session, created_at=created_at)
    db_session.add(_passing_metrics(version.id, computed_at=now))
    await db_session.commit()

    decision = await evaluate_and_promote(db_session, version.id, stage=StrategyStage.PAPER)

    assert decision.promote is False
    assert any("stage_track_record" in r for r in decision.reasons)


@pytest.mark.asyncio
async def test_promotes_and_retires_previous_champion_when_all_gates_pass(db_session):
    now = datetime.now(timezone.utc)
    old_created = now - timedelta(days=MIN_STAGE_DAYS + 10)

    champion, strategy_id = await _seed_version(
        db_session, created_at=old_created, champion_status=ChampionStatus.CHAMPION
    )
    db_session.add(
        StageMetrics(
            strategy_version_id=champion.id, stage=StrategyStage.PAPER,
            net_return_pct=0.05, max_drawdown_pct=0.10, win_rate=0.5, profit_factor=1.1,
            trade_count=120, oos_score=0.66, walk_forward_consistency=0.61, computed_at=now,
        )
    )
    db_session.add(_agent_with_fitness(champion.id, fitness=0.10, identifier="GEN01-AG0001"))

    challenger, _ = await _seed_version(
        db_session, created_at=now - timedelta(days=MIN_STAGE_DAYS + 1), strategy_id=strategy_id
    )
    db_session.add(_passing_metrics(challenger.id, computed_at=now))
    db_session.add(_agent_with_fitness(challenger.id, fitness=0.40, identifier="GEN02-AG0001"))
    await db_session.commit()

    decision = await evaluate_and_promote(db_session, challenger.id, stage=StrategyStage.PAPER)

    assert decision.promote is True, decision.reasons
    await db_session.refresh(challenger)
    await db_session.refresh(champion)
    assert challenger.champion_status == ChampionStatus.CHAMPION
    assert champion.champion_status == ChampionStatus.RETIRED
