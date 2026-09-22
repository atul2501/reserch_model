"""Wires app/backtesting/adversarial.py's run_adversarial_suite (previously
uncalled anywhere outside its own test) to a real StrategyVersion and
persists the result — this is the caller run_adversarial_suite never had.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtesting.adversarial import compute_robustness_score, run_adversarial_suite
from app.models.adversarial import AdversarialTestReport
from app.models.strategy import StrategyVersion
from app.schemas.strategy_dna import StrategyDNA


async def run_and_persist_adversarial_suite(
    db: AsyncSession,
    strategy_version_id: uuid.UUID,
    candles: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str,
    starting_equity: float,
    base_fee_rate: float,
    base_slippage_bps: float,
    n_dna_variants: int = 5,
    global_max_leverage: float = 5.0,
    global_max_position_size: float = 0.5,
    global_max_drawdown: float = 0.30,
    global_max_daily_loss: float = 0.10,
) -> AdversarialTestReport:
    """Loads `strategy_version_id`'s DNA, runs the full adversarial suite
    (risk-gated by default — see run_backtest's enforce_risk_engine), and
    persists an AdversarialTestReport. Caller commits."""
    version = await db.get(StrategyVersion, strategy_version_id)
    if version is None:
        raise ValueError(f"strategy_version {strategy_version_id} not found")
    dna = StrategyDNA.model_validate(version.dna)

    report = run_adversarial_suite(
        dna,
        candles,
        symbol=symbol,
        timeframe=timeframe,
        starting_equity=starting_equity,
        base_fee_rate=base_fee_rate,
        base_slippage_bps=base_slippage_bps,
        n_dna_variants=n_dna_variants,
        global_max_leverage=global_max_leverage,
        global_max_position_size=global_max_position_size,
        global_max_drawdown=global_max_drawdown,
        global_max_daily_loss=global_max_daily_loss,
    )

    scenario_breakdown: dict[str, dict[str, float]] = {}
    for r in report.scenario_results:
        existing = scenario_breakdown.get(r.scenario_name)
        if existing is None or r.result.max_drawdown_pct > existing["max_drawdown_pct"]:
            scenario_breakdown[r.scenario_name] = {
                "max_drawdown_pct": r.result.max_drawdown_pct,
                "net_return_pct": r.result.net_return_pct,
            }

    row = AdversarialTestReport(
        strategy_version_id=strategy_version_id,
        worst_case_max_drawdown_pct=report.worst_case_max_drawdown_pct,
        worst_case_net_return_pct=report.worst_case_net_return_pct,
        passed=report.passed,
        failure_reasons=report.failure_reasons,
        scenario_breakdown=scenario_breakdown,
        robustness_score=compute_robustness_score(report),
        computed_at=datetime.now(timezone.utc),
    )
    db.add(row)
    return row
