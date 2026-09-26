"""CLI wrapper for app.research.experiment_runner.run_baseline_vs_candidate.

    python -m scripts.run_experiment --name exit_fixed_pct_stop

Runs a baseline DNA and a candidate DNA against the same active epoch's
train+validation frame, persists both as real (non-overwriting) Experiment
rows, and prints the baseline/candidate comparison table. Writes to whatever
DATABASE_URL is configured (this project's normal Settings-driven config, not
a --db-path override — point DATABASE_URL at a snapshot copy for a dry run).
"""
from __future__ import annotations

import argparse
import asyncio

from app.core.database import AsyncSessionLocal
from app.research.experiment_runner import render_comparison, run_baseline_vs_candidate
from app.schemas.strategy_dna import (
    Condition, PositionSizing, RiskProfile, RuleSet, StopLossConfig, StrategyDNA, TakeProfitConfig,
)
from app.models.enums import StrategyFamily


def _ema_cross_dna(fast: int, slow: int, *, stop_loss: StopLossConfig) -> StrategyDNA:
    return StrategyDNA(
        strategy_family=StrategyFamily.TREND_FOLLOWING,
        indicators=[{"name": "ema", "params": {"period": fast}}, {"name": "ema", "params": {"period": slow}}],
        entry_rules=RuleSet(conditions=[Condition(feature=f"ema_{fast}", operator="gt", value=f"ema_{slow}")]),
        exit_rules=RuleSet(conditions=[Condition(feature=f"ema_{fast}", operator="lt", value=f"ema_{slow}")]),
        direction_mode="long_only",
        risk_profile=RiskProfile(max_leverage=2.0, max_position_fraction=0.5), leverage_limit=2.0,
        position_sizing=PositionSizing(fraction_of_equity=0.2),
        stop_loss=stop_loss, take_profit=TakeProfitConfig(enabled=False),
    )


BUILTIN_CONFIGS = {
    "exit_fixed_pct_stop": dict(
        baseline=_ema_cross_dna(5, 20, stop_loss=StopLossConfig(method="atr_multiple", value=3.0)),
        candidate=_ema_cross_dna(5, 20, stop_loss=StopLossConfig(method="fixed_pct", value=2.0)),
    ),
    "exit_tighter_atr_stop": dict(
        baseline=_ema_cross_dna(5, 20, stop_loss=StopLossConfig(method="atr_multiple", value=3.0)),
        candidate=_ema_cross_dna(5, 20, stop_loss=StopLossConfig(method="atr_multiple", value=1.5)),
    ),
}


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True, choices=sorted(BUILTIN_CONFIGS))
    args = parser.parse_args()

    cfg = BUILTIN_CONFIGS[args.name]
    async with AsyncSessionLocal() as db:
        baseline, candidate = await run_baseline_vs_candidate(
            db, baseline_dna=cfg["baseline"], candidate_dna=cfg["candidate"], name=args.name
        )
        await db.commit()
        print(render_comparison(args.name, baseline, candidate))


if __name__ == "__main__":
    asyncio.run(main())
