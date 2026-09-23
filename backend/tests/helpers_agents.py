"""Builders for decision-loop level tests (contexts, DNA, agents, cycle runner)."""
from __future__ import annotations

import uuid

from sqlalchemy import select

from app.agents.decision_loop import run_decision_cycle
from app.agents.lifecycle import create_generation
from app.core.config import get_settings
from app.models.agent import Agent
from app.models.enums import StrategyFamily, StrategyStage
from app.models.strategy import Strategy, StrategyVersion
from app.schemas.market_context import (
    MarketContext, MomentumFeatures, PriceActionFeatures, RegimeState, StructureFeatures, TrendFeatures,
    VolatilityFeatures, VolumeFeatures,
)
from app.schemas.strategy_dna import (
    Condition, CooldownConfig, PositionSizing, RiskProfile, RuleSet, StopLossConfig, StrategyDNA, TakeProfitConfig,
    TrailingStopConfig,
)

MINUTE = 60_000
T0 = 1_700_000_040_000  # minute-aligned


def make_context(
    i: int, close: float, *, rsi: float = 65.0, trend_strength: float = 0.01, high=None, low=None, open_=None,
    atr: float = 0.5, regime: str = "TREND_UP", roc: float = 1.0, macd_hist: float = 0.05, funding=None,
    timeframe: str = "1m", **overrides,
) -> MarketContext:
    open_time = T0 + i * MINUTE
    return MarketContext(
        symbol="SOL", timeframe=timeframe, candle_open_time=open_time, close_price=close,
        candle_open=open_ if open_ is not None else close,
        candle_high=high if high is not None else close, candle_low=low if low is not None else close,
        candle_close_time=open_time + MINUTE - 1, funding_rate=funding,
        trend=TrendFeatures(ema_fast=close, ema_slow=close - 1, sma_fast=close, sma_slow=close, ema_slope=0.1, trend_strength=trend_strength),
        momentum=MomentumFeatures(rsi_14=rsi, macd=0.1, macd_signal=0.05, macd_hist=macd_hist, roc_10=roc),
        volatility=VolatilityFeatures(atr_14=atr, realized_vol=0.02, volatility_percentile=0.5, bb_upper=close + 2, bb_middle=close, bb_lower=close - 2, bb_width=0.02),
        structure=StructureFeatures(),
        volume=VolumeFeatures(volume_sma_20=1000, volume_ratio=1.0, volume_spike=False, vwap=close),
        price_action=PriceActionFeatures(body=0.1, wick_ratio=0.1, candle_range=1.0, gap=0.0, is_momentum_candle=False),
        regime=RegimeState(regime=regime, confidence=0.8),
        **overrides,
    )


def make_dna(**over) -> StrategyDNA:
    base = dict(
        strategy_family=StrategyFamily.MOMENTUM,
        indicators=[{"name": "rsi", "params": {"period": 14}}],
        entry_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="gt", value=60)]),
        exit_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="lt", value=40)]),
        risk_profile=RiskProfile(max_leverage=1.0, max_position_fraction=0.5),
        position_sizing=PositionSizing(fraction_of_equity=0.1),
        stop_loss=StopLossConfig(method="atr_multiple", value=2.0),
        take_profit=TakeProfitConfig(method="risk_reward_multiple", value=2.0),
        trailing_stop=TrailingStopConfig(enabled=False),
        cooldown=CooldownConfig(),
        leverage_limit=1.0,
    )
    base.update(over)
    return StrategyDNA(**base)


async def make_agents(db, dnas, *, generation=100, stage: StrategyStage | None = None, balance=100.0) -> list[Agent]:
    ids = []
    for dna in dnas:
        strat = Strategy(code=f"S-{uuid.uuid4().hex[:10]}", family=dna.strategy_family, name="t")
        db.add(strat)
        await db.flush()
        kwargs = {"stage": stage} if stage is not None else {}
        v = StrategyVersion(strategy_id=strat.id, version=1, generation=1, dna=dna.model_dump(mode="json"), **kwargs)
        db.add(v)
        await db.flush()
        ids.append(v.id)
    await create_generation(db, generation_number=generation, strategy_version_ids=ids, starting_balance=balance)
    return list((await db.execute(select(Agent).where(Agent.generation == generation).order_by(Agent.identifier))).scalars().all())


async def cycle(db, engine, ctx, prev=None, *, generation=100, **kw):
    kw.setdefault("global_max_leverage", 5.0)
    kw.setdefault("global_max_position_size", 0.5)
    kw.setdefault("global_max_drawdown", 0.3)
    kw.setdefault("global_max_daily_loss", 0.1)
    kw.setdefault("market_data_age_seconds", 1.0)
    return await run_decision_cycle(db, engine, ctx, prev, generation=generation, council_decision_id=None, **kw)


def closed_position(db, agent, side=None):
    """A real (closed) Position row so Trade.position_id satisfies its foreign key
    (PostgreSQL enforces FKs; hand-made trade fixtures must too). Returns its id."""
    from datetime import datetime, timezone
    from app.models.enums import Side
    from app.models.trading import Position
    pos = Position(agent_id=agent.id, symbol="SOL", side=side or Side.LONG, quantity=1.0, entry_price=100.0,
                   is_open=False, opened_at=datetime.now(timezone.utc), closed_at=datetime.now(timezone.utc))
    db.add(pos)
    pos.id = uuid.uuid4()
    return pos.id


async def add_promotion_evidence(db, version_id, *, regime="ROBUST", robustness=0.8, backtest_return=0.30, paper_return=0.30,
                                 correlation=None):
    """The full evidence set the promotion gate demands beyond PnL: adversarial
    robustness, regime classification, a BACKTEST stage (for the reality gap)."""
    from datetime import datetime, timezone
    from app.models.adversarial import AdversarialTestReport
    from app.models.enums import StrategyStage
    from app.models.regime_validation import RegimeValidationReport
    from app.models.stage_metrics import StageMetrics
    now = datetime.now(timezone.utc)
    db.add(AdversarialTestReport(strategy_version_id=version_id, worst_case_max_drawdown_pct=0.1,
                                 worst_case_net_return_pct=-0.02, passed=True, failure_reasons=[], scenario_breakdown={},
                                 robustness_score=robustness, computed_at=now))
    db.add(RegimeValidationReport(strategy_version_id=version_id, per_regime={}, classification=regime,
                                  classification_reasoning=[], computed_at=now))
    db.add(StageMetrics(strategy_version_id=version_id, stage=StrategyStage.BACKTEST, net_return_pct=backtest_return,
                        max_drawdown_pct=0.05, win_rate=0.6, profit_factor=2.0, trade_count=200, computed_at=now))
    await db.flush()
