"""Wires run_adversarial_suite (previously uncalled anywhere outside its
own test) to a real StrategyVersion and persists an AdversarialTestReport
— this is the caller it never had."""
from __future__ import annotations

import uuid

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select

from app.evolution.adversarial_service import run_and_persist_adversarial_suite
from app.models.adversarial import AdversarialTestReport
from app.models.enums import StrategyFamily
from app.models.strategy import Strategy, StrategyVersion
from app.schemas.strategy_dna import Condition, RuleSet, StrategyDNA


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


async def _seed_strategy_version(db_session) -> uuid.UUID:
    code = f"STRAT-TEST-{uuid.uuid4().hex[:8]}"
    strategy = Strategy(code=code, family=StrategyFamily.TREND_FOLLOWING, name=code)
    db_session.add(strategy)
    await db_session.flush()
    dna = StrategyDNA(
        strategy_family=StrategyFamily.TREND_FOLLOWING,
        indicators=[{"name": "ema", "params": {"period": 12}}],
        entry_rules=RuleSet(conditions=[Condition(feature="trend_strength", operator="gt", value=0)]),
        exit_rules=RuleSet(conditions=[Condition(feature="trend_strength", operator="lt", value=-0.001)]),
    )
    version = StrategyVersion(strategy_id=strategy.id, version=1, generation=1, dna=dna.model_dump(mode="json"))
    db_session.add(version)
    await db_session.commit()
    return version.id


@pytest.mark.asyncio
async def test_run_and_persist_adversarial_suite_persists_a_report(db_session):
    version_id = await _seed_strategy_version(db_session)
    candles = _trending_candles(600)

    report = await run_and_persist_adversarial_suite(
        db_session, version_id, candles,
        symbol="SOL", timeframe="1m", starting_equity=100.0,
        base_fee_rate=0.00045, base_slippage_bps=2, n_dna_variants=2,
    )
    await db_session.commit()

    fetched = (
        await db_session.execute(
            select(AdversarialTestReport).where(AdversarialTestReport.strategy_version_id == version_id)
        )
    ).scalar_one()
    assert fetched.id == report.id
    assert 0.0 <= fetched.robustness_score <= 1.0
    assert isinstance(fetched.scenario_breakdown, dict)
    assert "baseline" in fetched.scenario_breakdown


@pytest.mark.asyncio
async def test_run_and_persist_adversarial_suite_raises_for_unknown_strategy_version(db_session):
    candles = _trending_candles(600)
    with pytest.raises(ValueError):
        await run_and_persist_adversarial_suite(
            db_session, uuid.uuid4(), candles,
            symbol="SOL", timeframe="1m", starting_equity=100.0,
            base_fee_rate=0.00045, base_slippage_bps=2,
        )
