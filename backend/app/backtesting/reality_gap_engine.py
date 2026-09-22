"""Full-lifecycle reality-gap report: Backtest -> Walk-Forward ->
Out-of-Sample -> Paper -> Shadow -> Small-Live -> Approved-Live, chained.

Built entirely on top of `stage_metrics_service.compute_reality_gap` /
`latest_stage_metrics` — this module never recomputes stage comparison math
itself, it just walks the full chain and persists the result.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.backtesting.stage_metrics_service import compute_reality_gap, latest_stage_metrics
from app.models.enums import StrategyStage
from app.models.reality_gap import RealityGapReport

FULL_CHAIN: list[StrategyStage] = [
    StrategyStage.BACKTEST,
    StrategyStage.WALK_FORWARD,
    StrategyStage.OUT_OF_SAMPLE,
    StrategyStage.PAPER,
    StrategyStage.SHADOW,
    StrategyStage.SMALL_LIVE,
    StrategyStage.APPROVED_LIVE,
]


@dataclass
class RealityGapChainReport:
    strategy_version_id: uuid.UUID
    stages_present: list[str] = field(default_factory=list)
    transitions: list[dict] = field(default_factory=list)
    cumulative_gap: dict | None = None


async def compute_full_reality_gap_chain(db: AsyncSession, strategy_version_id: uuid.UUID) -> RealityGapChainReport:
    """Compares every consecutive pair of stages this strategy version has
    actually reached StageMetrics for (skipping stages it hasn't reached
    yet, e.g. a PAPER-stage strategy has no SHADOW/LIVE comparisons), plus
    one cumulative first-reached-stage -> last-reached-stage comparison."""
    present_stages: list[StrategyStage] = []
    for stage in FULL_CHAIN:
        if await latest_stage_metrics(db, strategy_version_id, stage) is not None:
            present_stages.append(stage)

    transitions = [
        await compute_reality_gap(db, strategy_version_id, from_stage, to_stage)
        for from_stage, to_stage in zip(present_stages, present_stages[1:])
    ]

    cumulative_gap = None
    if len(present_stages) >= 2:
        cumulative_gap = await compute_reality_gap(db, strategy_version_id, present_stages[0], present_stages[-1])

    return RealityGapChainReport(
        strategy_version_id=strategy_version_id,
        stages_present=[s.value for s in present_stages],
        transitions=transitions,
        cumulative_gap=cumulative_gap,
    )


async def persist_reality_gap_report(db: AsyncSession, chain_report: RealityGapChainReport) -> RealityGapReport:
    """Insert-only — caller commits."""
    row = RealityGapReport(
        strategy_version_id=chain_report.strategy_version_id,
        stages_present=chain_report.stages_present,
        transitions=chain_report.transitions,
        cumulative_gap=chain_report.cumulative_gap,
        computed_at=datetime.now(timezone.utc),
    )
    db.add(row)
    return row
