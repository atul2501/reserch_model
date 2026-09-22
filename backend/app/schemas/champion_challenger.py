from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class ChallengerEvaluationOut(BaseModel):
    id: uuid.UUID
    strategy_version_id: uuid.UUID
    pipeline_stage: str
    entered_stage_at: datetime
    min_observation_days_required: int | None
    metrics_snapshot: dict
    blocking_reasons: list[str]
    computed_at: datetime

    model_config = {"from_attributes": True}


class ChampionSummaryOut(BaseModel):
    strategy_id: uuid.UUID
    strategy_code: str
    strategy_family: str
    champion_version_id: uuid.UUID
    champion_version_number: int


class EvolutionEventOut(BaseModel):
    id: uuid.UUID
    event_type: str
    parent_strategy_version_id: uuid.UUID | None
    child_strategy_version_id: uuid.UUID | None
    generation: int
    accepted: bool | None
    rejection_reason: str | None
    validation_result: dict
    created_at: datetime

    model_config = {"from_attributes": True}
