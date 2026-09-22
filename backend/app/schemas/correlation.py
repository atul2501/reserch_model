from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class AgentPairCorrelationOut(BaseModel):
    id: uuid.UUID
    generation: int
    agent_id_a: uuid.UUID
    agent_id_b: uuid.UUID
    strategy_family_a: str
    strategy_family_b: str
    dna_similarity: float
    feature_similarity: float
    entry_condition_similarity: float
    exit_condition_similarity: float
    trade_direction_correlation: float | None
    return_correlation: float | None
    position_overlap: float | None
    trade_timing_similarity: float | None
    composite_correlation: float
    computed_at: datetime

    model_config = {"from_attributes": True}


class StrategyFamilyCorrelationOut(BaseModel):
    family_a: str
    family_b: str
    mean_correlation: float
    member_pair_count: int

    model_config = {"from_attributes": True}


class CorrelationConvergenceOut(BaseModel):
    generation: int
    population_diversity_score: float
    mean_pairwise_correlation: float
    pct_agents_above_max_correlation: float
    family_distribution: dict[str, int]
    diversity_pressure_applied: bool
    actions_taken: dict
    computed_at: datetime

    model_config = {"from_attributes": True}
