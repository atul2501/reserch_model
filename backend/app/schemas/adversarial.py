from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class ScenarioBreakdownOut(BaseModel):
    max_drawdown_pct: float
    net_return_pct: float


class AdversarialTestReportOut(BaseModel):
    id: uuid.UUID
    strategy_version_id: uuid.UUID
    worst_case_max_drawdown_pct: float
    worst_case_net_return_pct: float
    passed: bool
    failure_reasons: list[str]
    scenario_breakdown: dict[str, ScenarioBreakdownOut]
    robustness_score: float
    computed_at: datetime

    model_config = {"from_attributes": True}
