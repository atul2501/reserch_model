from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class StageTransitionGapOut(BaseModel):
    from_stage: str
    to_stage: str
    net_return_pct: dict
    max_drawdown_pct: dict
    win_rate: dict
    profit_factor: dict
    total_fees: dict
    total_funding: dict
    total_slippage_cost: dict
    avg_trade_net_pnl: dict
    avg_latency_ms: dict
    missed_trade_pct: dict
    avg_signal_to_fill_seconds: dict


class RealityGapChainReportOut(BaseModel):
    strategy_version_id: uuid.UUID
    stages_present: list[str]
    transitions: list[StageTransitionGapOut]
    cumulative_gap: StageTransitionGapOut | None

    model_config = {"from_attributes": True}


class RealityGapReportOut(BaseModel):
    id: uuid.UUID
    strategy_version_id: uuid.UUID
    stages_present: list[str]
    transitions: list[dict]
    cumulative_gap: dict | None
    computed_at: datetime

    model_config = {"from_attributes": True}
