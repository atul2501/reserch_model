"""Computes and persists per-generation strategy correlation — DNA-
structural similarity (correlation.py, extending diversity.py's
dna_distance) plus behavioral correlation derived from real Trade rows
(direction/return/timing/position-overlap).

Behavioral correlation is batch-loaded once per generation and computed
with vectorized pandas operations (pivot + .corr() / matrix multiply), not
one query per agent pair — at 500 agents that's ~125k pairs, and O(pairs)
DB I/O at that scale is not viable.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.evolution.correlation import (
    _jaccard, feature_set, ruleset_signature, ruleset_signature_similarity,
)
from app.evolution.diversity import dna_signature, family_distribution, population_diversity_score, signature_distance
from app.models.agent import Agent
from app.models.correlation import AgentCorrelation, CorrelationConvergenceSnapshot, StrategyFamilyCorrelation
from app.models.strategy import StrategyVersion
from app.models.trading import Trade
from app.schemas.strategy_dna import StrategyDNA

DEFAULT_TOP_N_PAIRS = 200


@dataclass
class PairCorrelation:
    agent_id_a: uuid.UUID
    agent_id_b: uuid.UUID
    family_a: str
    family_b: str
    dna_similarity: float
    feature_similarity: float
    entry_condition_similarity: float
    exit_condition_similarity: float
    trade_direction_correlation: float | None
    return_correlation: float | None
    position_overlap: float | None
    trade_timing_similarity: float | None
    composite_correlation: float


@dataclass
class GenerationCorrelationReport:
    generation: int
    pairs: list[PairCorrelation] = field(default_factory=list)
    population_diversity_score: float = 1.0
    mean_pairwise_correlation: float = 0.0
    pct_agents_above_max_correlation: float = 0.0
    family_distribution: dict[str, int] = field(default_factory=dict)
    family_pair_correlations: dict[tuple[str, str], tuple[float, int]] = field(default_factory=dict)
    # Mean composite correlation of each agent to ALL its peers (computed over the
    # full pair set, not just the persisted top-N) — feeds fitness as soft diversity pressure.
    agent_mean_correlation: dict[uuid.UUID, float] = field(default_factory=dict)


# Weights for the composite score — behavioral dimensions (does this agent
# actually trade like that one) weighted higher than raw DNA-parameter
# similarity (two agents can share a family/parameters yet never actually
# overlap in market behavior, or vice versa).
_COMPOSITE_WEIGHTS = {
    "dna_similarity": 0.15,
    "feature_similarity": 0.10,
    "entry_condition_similarity": 0.10,
    "exit_condition_similarity": 0.10,
    "trade_direction_correlation": 0.20,
    "return_correlation": 0.20,
    "position_overlap": 0.10,
    "trade_timing_similarity": 0.05,
}


def _composite(values: dict[str, float | None]) -> float:
    total_weight = 0.0
    weighted_sum = 0.0
    for key, weight in _COMPOSITE_WEIGHTS.items():
        value = values.get(key)
        if value is None:
            continue
        weighted_sum += weight * value
        total_weight += weight
    return weighted_sum / total_weight if total_weight else 0.0


async def compute_generation_correlation_report(
    db: AsyncSession,
    *,
    generation: int,
    bucket: str = "1h",
    lookback_days: int = 30,
    max_strategy_correlation: float = 0.80,
    top_n_pairs: int = DEFAULT_TOP_N_PAIRS,
    now: datetime | None = None,
) -> GenerationCorrelationReport:
    """`now`, when given, overrides real wall-clock time for the lookback window (mirrors
    `app.research.pipeline.evaluate_gates`'s existing `now` override pattern) - so a replay
    of a past generation computes correlation from trades as of that generation's own time,
    not real "today"."""
    agents = (await db.execute(select(Agent).where(Agent.generation == generation))).scalars().all()
    if len(agents) < 2:
        return GenerationCorrelationReport(generation=generation)

    version_ids = {a.strategy_version_id for a in agents}
    versions = (await db.execute(select(StrategyVersion).where(StrategyVersion.id.in_(version_ids)))).scalars().all()
    dna_by_version_id = {v.id: StrategyDNA.model_validate(v.dna) for v in versions}
    dna_by_agent_id = {a.id: dna_by_version_id[a.strategy_version_id] for a in agents}
    family_by_agent_id = {a.id: dna_by_agent_id[a.id].strategy_family.value for a in agents}

    agent_ids = [a.id for a in agents]
    direction_corr, return_corr, timing_corr, overlap_jaccard = await _compute_behavioral_correlations(
        db, agent_ids=agent_ids, bucket=bucket, lookback_days=lookback_days, now=now
    )

    # The pairwise build is CPU-bound (~125k pairs for 500 agents): per-agent structures are computed ONCE, matrix
    # lookups are O(1) numpy indexing, and the whole thing runs off the event loop (lease heartbeats keep beating).
    return await asyncio.to_thread(
        _build_report, generation, agent_ids, dna_by_agent_id, family_by_agent_id,
        (direction_corr, return_corr, timing_corr, overlap_jaccard), max_strategy_correlation, top_n_pairs,
    )


class _Matrix:
    """O(1) pair lookups into a (possibly missing) correlation DataFrame."""

    def __init__(self, matrix: pd.DataFrame | None, agent_ids: list[uuid.UUID]) -> None:
        self._values = None
        if matrix is not None:
            self._values = matrix.reindex(index=agent_ids, columns=agent_ids).to_numpy(dtype=float)

    def get(self, i: int, j: int) -> float | None:
        if self._values is None:
            return None
        v = self._values[i, j]
        return None if np.isnan(v) else float(v)


def _build_report(
    generation: int, agent_ids: list[uuid.UUID], dna_by_agent_id: dict, family_by_agent_id: dict, matrices: tuple,
    max_strategy_correlation: float, top_n_pairs: int,
) -> GenerationCorrelationReport:
    direction_m, return_m, timing_m, overlap_m = (_Matrix(m, agent_ids) for m in matrices)
    dnas = [dna_by_agent_id[a] for a in agent_ids]
    sigs = [dna_signature(d) for d in dnas]
    feats = [feature_set(d) for d in dnas]
    entries = [ruleset_signature(d.entry_rules) for d in dnas]
    exits = [ruleset_signature(d.exit_rules) for d in dnas]

    pairs: list[PairCorrelation] = []
    corr_sum: dict[uuid.UUID, float] = {aid: 0.0 for aid in agent_ids}
    for i in range(len(agent_ids)):
        for j in range(i + 1, len(agent_ids)):
            id_a, id_b = agent_ids[i], agent_ids[j]
            values = {
                "dna_similarity": 1.0 - signature_distance(sigs[i], sigs[j]),
                "feature_similarity": _jaccard(feats[i], feats[j]),
                "entry_condition_similarity": ruleset_signature_similarity(entries[i], entries[j]),
                "exit_condition_similarity": ruleset_signature_similarity(exits[i], exits[j]),
                "trade_direction_correlation": direction_m.get(i, j),
                "return_correlation": return_m.get(i, j),
                "position_overlap": overlap_m.get(i, j),
                "trade_timing_similarity": timing_m.get(i, j),
            }
            composite = _composite(values)
            pairs.append(
                PairCorrelation(
                    agent_id_a=id_a, agent_id_b=id_b, family_a=family_by_agent_id[id_a], family_b=family_by_agent_id[id_b],
                    dna_similarity=values["dna_similarity"], feature_similarity=values["feature_similarity"],
                    entry_condition_similarity=values["entry_condition_similarity"],
                    exit_condition_similarity=values["exit_condition_similarity"],
                    trade_direction_correlation=values["trade_direction_correlation"],
                    return_correlation=values["return_correlation"], position_overlap=values["position_overlap"],
                    trade_timing_similarity=values["trade_timing_similarity"], composite_correlation=composite,
                )
            )
            corr_sum[id_a] += composite
            corr_sum[id_b] += composite

    mean_correlation = sum(p.composite_correlation for p in pairs) / len(pairs) if pairs else 0.0
    above_threshold_agent_ids: set[uuid.UUID] = set()
    for p in pairs:
        if p.composite_correlation > max_strategy_correlation:
            above_threshold_agent_ids.add(p.agent_id_a)
            above_threshold_agent_ids.add(p.agent_id_b)
    pct_above = len(above_threshold_agent_ids) / len(agent_ids) if agent_ids else 0.0

    family_pairs: dict[tuple[str, str], list[float]] = {}
    for p in pairs:
        key = tuple(sorted((p.family_a, p.family_b)))
        family_pairs.setdefault(key, []).append(p.composite_correlation)
    family_pair_correlations = {k: (sum(v) / len(v), len(v)) for k, v in family_pairs.items()}

    pairs.sort(key=lambda p: p.composite_correlation, reverse=True)

    return GenerationCorrelationReport(
        generation=generation,
        pairs=pairs[:top_n_pairs],
        population_diversity_score=population_diversity_score(dnas, sigs),
        mean_pairwise_correlation=mean_correlation,
        pct_agents_above_max_correlation=pct_above,
        family_distribution=family_distribution(dnas),
        family_pair_correlations=family_pair_correlations,
        agent_mean_correlation={aid: total / (len(agent_ids) - 1) for aid, total in corr_sum.items()},
    )


def _lookup(matrix: pd.DataFrame | None, id_a: uuid.UUID, id_b: uuid.UUID) -> float | None:
    if matrix is None or id_a not in matrix.index or id_b not in matrix.columns:
        return None
    value = matrix.loc[id_a, id_b]
    if pd.isna(value):
        return None
    return float(value)


async def _compute_behavioral_correlations(
    db: AsyncSession, *, agent_ids: list[uuid.UUID], bucket: str, lookback_days: int, now: datetime | None = None
) -> tuple[pd.DataFrame | None, pd.DataFrame | None, pd.DataFrame | None, pd.DataFrame | None]:
    """Single batch query for the whole generation, then vectorized pandas
    correlation — not one query per pair."""
    now_ref = now or datetime.now(timezone.utc)
    since = now_ref - timedelta(days=lookback_days)
    trades = (
        await db.execute(
            select(Trade.agent_id, Trade.side, Trade.net_pnl, Trade.opened_at, Trade.closed_at).where(
                Trade.agent_id.in_(agent_ids), Trade.closed_at >= since, Trade.closed_at <= now_ref
            )
        )
    ).all()
    if not trades:
        return None, None, None, None

    df = pd.DataFrame(trades, columns=["agent_id", "side", "net_pnl", "opened_at", "closed_at"])
    df["closed_at"] = pd.to_datetime(df["closed_at"], utc=True)
    df["opened_at"] = pd.to_datetime(df["opened_at"], utc=True)
    df["bucket"] = df["closed_at"].dt.floor(bucket)
    df["direction"] = df["side"].map(lambda s: 1.0 if str(s).endswith("LONG") else -1.0)

    direction_wide = df.pivot_table(index="bucket", columns="agent_id", values="direction", aggfunc="mean")
    return_wide = df.pivot_table(index="bucket", columns="agent_id", values="net_pnl", aggfunc="sum")
    timing_wide = df.pivot_table(index="bucket", columns="agent_id", values="net_pnl", aggfunc="count")

    direction_corr = direction_wide.corr(min_periods=2)
    return_corr = return_wide.fillna(0.0).corr(min_periods=2)
    timing_corr = timing_wide.fillna(0.0).corr(min_periods=2)

    overlap_jaccard = _position_overlap_jaccard(df, agent_ids, bucket)

    return direction_corr, return_corr, timing_corr, overlap_jaccard


def _position_overlap_jaccard(df: pd.DataFrame, agent_ids: list[uuid.UUID], bucket: str) -> pd.DataFrame:
    """Expands each trade's [opened_at, closed_at] into the buckets it
    spans, builds a boolean (bucket x agent) presence matrix, and computes
    pairwise Jaccard overlap via matrix multiplication — vectorized, not a
    per-pair loop."""
    rows = []
    for agent_id, opened_at, closed_at in zip(df["agent_id"], df["opened_at"], df["closed_at"]):
        for b in pd.date_range(opened_at.floor(bucket), closed_at.floor(bucket), freq=bucket):
            rows.append((agent_id, b))
    if not rows:
        return pd.DataFrame(0, index=agent_ids, columns=agent_ids)

    presence = pd.DataFrame(rows, columns=["agent_id", "bucket"]).drop_duplicates()
    presence["present"] = 1
    wide = presence.pivot_table(index="bucket", columns="agent_id", values="present", fill_value=0)
    wide = wide.reindex(columns=agent_ids, fill_value=0)

    matrix = wide.to_numpy(dtype=float)
    intersection = matrix.T @ matrix
    totals = matrix.sum(axis=0)
    union = totals[:, None] + totals[None, :] - intersection
    with np.errstate(divide="ignore", invalid="ignore"):
        jaccard = np.where(union > 0, intersection / union, 0.0)

    return pd.DataFrame(jaccard, index=wide.columns, columns=wide.columns)


async def persist_generation_correlation(db: AsyncSession, report: GenerationCorrelationReport) -> None:
    """Insert-only — never overwrites a prior generation's rows. Caller
    commits."""
    now = datetime.now(timezone.utc)
    for p in report.pairs:
        db.add(
            AgentCorrelation(
                generation=report.generation,
                agent_id_a=p.agent_id_a,
                agent_id_b=p.agent_id_b,
                strategy_family_a=p.family_a,
                strategy_family_b=p.family_b,
                dna_similarity=p.dna_similarity,
                feature_similarity=p.feature_similarity,
                entry_condition_similarity=p.entry_condition_similarity,
                exit_condition_similarity=p.exit_condition_similarity,
                trade_direction_correlation=p.trade_direction_correlation,
                return_correlation=p.return_correlation,
                position_overlap=p.position_overlap,
                trade_timing_similarity=p.trade_timing_similarity,
                composite_correlation=p.composite_correlation,
                computed_at=now,
            )
        )
    for (family_a, family_b), (mean_corr, count) in report.family_pair_correlations.items():
        db.add(
            StrategyFamilyCorrelation(
                generation=report.generation,
                family_a=family_a,
                family_b=family_b,
                mean_correlation=mean_corr,
                member_pair_count=count,
                computed_at=now,
            )
        )


@dataclass
class DiversityPressureAction:
    diversity_pressure_applied: bool
    mutation_rate_multiplier: float
    preserve_family_codes: set[str] = field(default_factory=set)
    families_to_inject: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


async def apply_diversity_pressure(
    db: AsyncSession,
    *,
    report: GenerationCorrelationReport,
    max_strategy_correlation: float = 0.80,
    min_strategy_diversity: float = 0.60,
) -> DiversityPressureAction:
    """Pure signal generator for app/evolution/breeding.py to consume:
    a mutation-rate multiplier and which families to preserve/inject.
    NEVER touches Agent.status — correlation is a diversity/selection
    signal only, never a kill signal (see tests/test_correlation.py, which
    asserts no AgentStatus.DEAD write occurs anywhere in this module's
    call graph). Persists one CorrelationConvergenceSnapshot row — the
    generation-over-generation convergence history. Caller commits."""
    reasons: list[str] = []
    if report.population_diversity_score < min_strategy_diversity:
        reasons.append(
            f"population_diversity_score {report.population_diversity_score:.3f} < floor {min_strategy_diversity}"
        )
    if report.mean_pairwise_correlation > max_strategy_correlation:
        reasons.append(
            f"mean_pairwise_correlation {report.mean_pairwise_correlation:.3f} > max {max_strategy_correlation}"
        )
    if report.pct_agents_above_max_correlation > 0.0:
        reasons.append(
            f"{report.pct_agents_above_max_correlation:.1%} of agents have a pair above max_strategy_correlation"
        )
    pressure_needed = bool(reasons)

    # Preserve minority families (fewer members than the population
    # average) so breeding doesn't let them go extinct while correcting
    # for the dominant, highly-correlated family/families.
    total_members = sum(report.family_distribution.values())
    family_count = len(report.family_distribution)
    avg_members = (total_members / family_count) if family_count else 0.0
    preserve = {fam for fam, count in report.family_distribution.items() if count < avg_members}

    action = DiversityPressureAction(
        diversity_pressure_applied=pressure_needed,
        mutation_rate_multiplier=1.5 if pressure_needed else 1.0,
        preserve_family_codes=preserve,
        families_to_inject=sorted(preserve) if pressure_needed else [],
        reasons=reasons,
    )

    db.add(
        CorrelationConvergenceSnapshot(
            generation=report.generation,
            population_diversity_score=report.population_diversity_score,
            mean_pairwise_correlation=report.mean_pairwise_correlation,
            pct_agents_above_max_correlation=report.pct_agents_above_max_correlation,
            family_distribution=report.family_distribution,
            diversity_pressure_applied=pressure_needed,
            actions_taken={
                "mutation_rate_multiplier": action.mutation_rate_multiplier,
                "preserve_family_codes": sorted(preserve),
                "families_to_inject": action.families_to_inject,
                "reasons": reasons,
            },
            computed_at=datetime.now(timezone.utc),
        )
    )

    return action
