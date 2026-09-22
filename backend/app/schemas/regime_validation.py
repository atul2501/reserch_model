from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class RegimeStatsOut(BaseModel):
    trade_count: int
    pnl: float
    roi: float | None
    profit_factor: float | None
    win_rate: float | None
    max_drawdown_pct: float
    expectancy: float | None


class RegimeValidationReportOut(BaseModel):
    id: uuid.UUID
    strategy_version_id: uuid.UUID
    per_regime: dict[str, RegimeStatsOut]
    classification: str
    classification_reasoning: list[str]
    computed_at: datetime

    model_config = {"from_attributes": True}
