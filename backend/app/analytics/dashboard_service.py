"""Read-only aggregation queries for the observability dashboard (the /analytics page).

Every function here is SELECT-only. This module never writes to the database and never
touches trading, fitness-calculation, breeding, promotion, or execution logic - it only reads
and reshapes what those subsystems have already persisted (see app/analytics/fitness_engine.py,
app/evolution/breeding.py, app/evolution/champion_challenger_service.py for the real logic).

Every function that can legitimately have nothing to report returns an explicit
insufficient_data / insufficient_history marker instead of a fabricated zero - callers
(app/api/routes/dashboard.py) pass these straight through, and the frontend renders them as
"Insufficient data" rather than a misleading number.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.agent import Agent
from app.models.analytics import FitnessForwardPerformance
from app.models.enums import AgentStatus, ChampionStatus
from app.models.metrics import FitnessScore
from app.models.research import Experiment, ResearchEpoch
from app.models.strategy import Generation, Strategy, StrategyVersion
from app.models.trading import Trade

# Mirrors app.analytics.fitness_engine.MIN_TRADES_FOR_FULL_CONFIDENCE - duplicated (not
# imported) because fitness_engine's constant is private to the fitness-calculation module by
# convention; this module only ever READS the effect of that constant (weights_used + stored
# scores), never feeds it back into scoring.
_MIN_TRADES_FOR_FULL_CONFIDENCE = 30

_EQUITY_RANGES = {"1H": timedelta(hours=1), "6H": timedelta(hours=6), "24H": timedelta(hours=24),
                   "3D": timedelta(days=3), "7D": timedelta(days=7), "30D": timedelta(days=30)}
_EQUITY_POINT_CAP = 3000  # never ship more raw points to the browser than this (spec Phase 21)
_AGENT_METRICS_SAFETY_CAP = 5000  # population sizes today are in the hundreds; this is a guard rail, not a real limit


async def _latest_generation(db: AsyncSession) -> Generation | None:
    return (await db.execute(select(Generation).order_by(Generation.number.desc()).limit(1))).scalar_one_or_none()


def _agent_age_days(agent: Agent, now: datetime) -> float:
    end = agent.death_timestamp or now
    return max((end - agent.created_at).total_seconds() / 86400.0, 1 / 24)  # floor at 1h to avoid divide-by-~0


# --------------------------------------------------------------------------- #
# Phase 2 - overview KPIs
# --------------------------------------------------------------------------- #
async def get_overview(db: AsyncSession) -> dict:
    settings = get_settings()
    gen = await _latest_generation(db)
    gen_no = gen.number if gen else None

    by_status: dict[str, dict] = {}
    if gen_no is not None:
        rows = (await db.execute(
            select(Agent.status, func.count(), func.coalesce(func.sum(Agent.equity), 0.0))
            .where(Agent.generation == gen_no).group_by(Agent.status)
        )).all()
        by_status = {s.value: {"count": n, "equity": float(e)} for s, n, e in rows}

    total_trades, wins, total_pnl, hold_min, hold_max, hold_avg = (await db.execute(
        select(func.count(), func.coalesce(func.sum(case((Trade.net_pnl > 0, 1), else_=0)), 0),
               func.coalesce(func.sum(Trade.net_pnl), 0.0),
               func.min(Trade.holding_seconds), func.max(Trade.holding_seconds), func.avg(Trade.holding_seconds))
    )).one()

    champion_count = (await db.execute(
        select(func.count()).select_from(StrategyVersion).where(StrategyVersion.champion_status == ChampionStatus.CHAMPION)
    )).scalar_one()

    equity_curve = await get_equity_curve(db, "ALL")

    return {
        "total_pnl": float(total_pnl),
        "current_equity": sum(v["equity"] for v in by_status.values()) if by_status else None,
        "starting_equity": gen.total_capital_allocated if gen else None,
        "max_drawdown_pct": equity_curve.get("max_drawdown_pct"),
        "win_rate": (wins / total_trades) if total_trades else None,
        "total_trades": total_trades,
        # trade holding time in seconds (None with no trades, never a fabricated 0)
        "hold_seconds_min": int(hold_min) if hold_min is not None else None,
        "hold_seconds_max": int(hold_max) if hold_max is not None else None,
        "hold_seconds_avg": float(hold_avg) if hold_avg is not None else None,
        "active_agents": by_status.get(AgentStatus.ACTIVE.value, {}).get("count", 0),
        "dead_agents": by_status.get(AgentStatus.DEAD.value, {}).get("count", 0),
        "current_generation": gen_no,
        "champion_count": champion_count,
        "trading_mode": settings.trading_mode.value,
    }


# --------------------------------------------------------------------------- #
# Phase 3 - equity curve
# --------------------------------------------------------------------------- #
async def get_equity_curve(db: AsyncSession, range_key: str) -> dict:
    range_key = (range_key or "ALL").upper()
    gen = await _latest_generation(db)
    if gen is None:
        return {"insufficient_data": True, "range": range_key, "points": []}

    now = datetime.now(timezone.utc)
    if range_key == "ALL":
        start = gen.created_at
    elif range_key in _EQUITY_RANGES:
        start = now - _EQUITY_RANGES[range_key]
    else:
        return {"insufficient_data": True, "range": range_key, "points": [], "error": "unknown range"}

    gen_agent_ids = select(Agent.id).where(Agent.generation == gen.number)
    trades = (await db.execute(
        select(Trade.closed_at, Trade.net_pnl)
        .where(Trade.agent_id.in_(gen_agent_ids), Trade.closed_at >= start)
        .order_by(Trade.closed_at)
    )).all()
    if not trades:
        return {"insufficient_data": True, "range": range_key, "points": []}

    # Downsample if needed - keep every Nth point, always keep the last one.
    step = max(1, len(trades) // _EQUITY_POINT_CAP)

    baseline = gen.total_capital_allocated
    equity = baseline
    peak = baseline
    max_dd = 0.0
    points = [{"t": start.isoformat(), "equity": baseline, "drawdown": 0.0}]
    last_i = len(trades) - 1
    for i, (closed_at, net_pnl) in enumerate(trades):
        equity += net_pnl
        peak = max(peak, equity)
        dd = (peak - equity) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
        if i % step == 0 or i == last_i:
            points.append({"t": closed_at.isoformat(), "equity": equity, "drawdown": dd})

    return {"insufficient_data": False, "range": range_key, "points": points,
            "starting_equity": baseline, "current_equity": equity, "max_drawdown_pct": max_dd}


# --------------------------------------------------------------------------- #
# Phases 7, 8, 9, 10, 12, 14 - one shared per-agent payload
# --------------------------------------------------------------------------- #
_AGENT_SORT_KEYS = {
    "fitness": "fitness", "pnl": "pnl", "future_pnl": "future_pnl", "expectancy": "expectancy",
    "profit_factor": "profit_factor", "drawdown": "max_drawdown", "oos_score": "oos_score",
    "trades_per_day": "trades_per_day",
}


async def get_agent_metrics(
    db: AsyncSession, *, generation: int | None = None, status: str | None = None,
    strategy_family: str | None = None, sort_by: str = "fitness", sort_dir: str = "desc",
    limit: int = 100, offset: int = 0,
) -> dict:
    stmt = select(Agent).order_by(Agent.id).limit(_AGENT_METRICS_SAFETY_CAP)
    if generation is not None:
        stmt = stmt.where(Agent.generation == generation)
    if status is not None:
        stmt = stmt.where(Agent.status == status)
    agents = (await db.execute(stmt)).scalars().all()
    if not agents:
        return {"total": 0, "rows": [], "capped": False}
    capped = len(agents) >= _AGENT_METRICS_SAFETY_CAP

    version_ids = {a.strategy_version_id for a in agents}
    version_rows = (await db.execute(
        select(StrategyVersion.id, StrategyVersion.champion_status, Strategy.family)
        .join(Strategy, Strategy.id == StrategyVersion.strategy_id)
        .where(StrategyVersion.id.in_(version_ids))
    )).all()
    version_info = {vid: {"champion_status": cs.value if cs else None, "family": fam.value} for vid, cs, fam in version_rows}

    if strategy_family is not None:
        agents = [a for a in agents if version_info.get(a.strategy_version_id, {}).get("family") == strategy_family]
    if not agents:
        return {"total": 0, "rows": [], "capped": capped}
    agent_ids = [a.id for a in agents]

    trade_rows = (await db.execute(
        select(Trade.agent_id, func.count(), func.coalesce(func.sum(Trade.net_pnl), 0.0),
               func.coalesce(func.sum(case((Trade.net_pnl > 0, 1), else_=0)), 0),
               func.coalesce(func.sum(case((Trade.net_pnl > 0, Trade.net_pnl), else_=0.0)), 0.0),
               func.coalesce(func.sum(case((Trade.net_pnl < 0, Trade.net_pnl), else_=0.0)), 0.0))
        .where(Trade.agent_id.in_(agent_ids)).group_by(Trade.agent_id)
    )).all()
    trade_by_agent = {}
    for aid, n, pnl, wins, gross_win, gross_loss in trade_rows:
        pf = None
        if gross_loss:
            pf = min(gross_win / abs(gross_loss), 3.0)  # PROFIT_FACTOR_CAP, mirrors fitness_engine.py
        elif gross_win > 0:
            pf = 3.0
        trade_by_agent[aid] = {"trade_count": n, "pnl": float(pnl), "win_rate": (wins / n) if n else None,
                                "expectancy": (float(pnl) / n) if n else None, "profit_factor": pf}

    latest_fs = (select(FitnessScore.agent_id, func.max(FitnessScore.as_of).label("max_as_of"))
                 .where(FitnessScore.agent_id.in_(agent_ids)).group_by(FitnessScore.agent_id).subquery())
    fs_rows = (await db.execute(
        select(FitnessScore).join(latest_fs, (FitnessScore.agent_id == latest_fs.c.agent_id) & (FitnessScore.as_of == latest_fs.c.max_as_of))
    )).scalars().all()
    fitness_by_agent = {r.agent_id: r for r in fs_rows}

    latest_ffp = (select(FitnessForwardPerformance.agent_id, func.max(FitnessForwardPerformance.as_of).label("max_as_of"))
                  .where(FitnessForwardPerformance.agent_id.in_(agent_ids), FitnessForwardPerformance.censor_reason == "none")
                  .group_by(FitnessForwardPerformance.agent_id).subquery())
    ffp_rows = (await db.execute(
        select(FitnessForwardPerformance)
        .join(latest_ffp, (FitnessForwardPerformance.agent_id == latest_ffp.c.agent_id) & (FitnessForwardPerformance.as_of == latest_ffp.c.max_as_of))
    )).scalars().all()
    future_pnl_by_agent = {r.agent_id: r.future_net_pnl for r in ffp_rows}

    now = datetime.now(timezone.utc)
    rows = []
    for a in agents:
        age_days = _agent_age_days(a, now)
        t = trade_by_agent.get(a.id, {"trade_count": 0, "pnl": 0.0, "win_rate": None, "expectancy": None, "profit_factor": None})
        fs = fitness_by_agent.get(a.id)
        vinfo = version_info.get(a.strategy_version_id, {})
        rows.append({
            "agent_id": str(a.id), "identifier": a.identifier, "generation": a.generation,
            "strategy_family": vinfo.get("family"), "status": a.status.value,
            "champion_status": vinfo.get("champion_status"),
            "fitness": fs.fitness if fs is not None else a.fitness,
            "oos_score": fs.oos_score if fs is not None else None,
            "risk_score": fs.risk_score if fs is not None else None,
            "pnl": t["pnl"], "future_pnl": future_pnl_by_agent.get(a.id),
            "expectancy": t["expectancy"], "profit_factor": t["profit_factor"], "win_rate": t["win_rate"],
            "max_drawdown": a.max_drawdown, "trade_count": t["trade_count"],
            "trades_per_day": t["trade_count"] / age_days,
        })

    field = _AGENT_SORT_KEYS.get(sort_by, "fitness")
    rows.sort(key=lambda r: (r[field] is not None, r[field] if r[field] is not None else 0), reverse=(sort_dir != "asc"))

    return {"total": len(rows), "rows": rows[offset: offset + limit], "capped": capped}


# --------------------------------------------------------------------------- #
# Phase 6 - fitness component contribution (actual, not configured-weight-only)
# --------------------------------------------------------------------------- #
_FITNESS_COMPONENT_FIELDS = [
    "return_score", "risk_score", "consistency_score", "robustness_score", "oos_score",
    "drawdown_penalty", "instability_penalty", "correlation_penalty", "expectancy_score",
    "regime_score", "adversarial_score",
]
_PENALTY_FIELDS = {"drawdown_penalty", "instability_penalty", "correlation_penalty"}
# FitnessScore column name -> the matching key in FitnessWeights.as_dict() / weights_used JSON
_WEIGHT_KEY = {
    "return_score": "return_weight", "risk_score": "risk_weight", "consistency_score": "consistency_weight",
    "robustness_score": "robustness_weight", "oos_score": "oos_weight", "drawdown_penalty": "drawdown_penalty_weight",
    "instability_penalty": "instability_penalty_weight", "correlation_penalty": "correlation_penalty_weight",
    "expectancy_score": "expectancy_weight", "regime_score": "regime_weight", "adversarial_score": "adversarial_weight",
    "inactivity_penalty": "inactivity_penalty_weight", "death_penalty": "death_penalty_weight",
}


async def get_fitness_components(db: AsyncSession, *, generation: int | None = None) -> dict:
    """Reconstructs the SIGNED, WEIGHTED contribution of every term in
    app.analytics.fitness_engine.compute_fitness's sum, from persisted FitnessScore rows (the
    real per-agent scores, not just the configured weights). inactivity_penalty/death_penalty
    aren't persisted columns on FitnessScore, so they're recomputed here from Agent.trade_count/
    status using the exact same formula fitness_engine.py uses - this makes the reconstruction
    sum to the real total fitness, not just 10 of its 12 terms."""
    latest_fs = (select(FitnessScore.agent_id, func.max(FitnessScore.as_of).label("max_as_of"))
                 .group_by(FitnessScore.agent_id).subquery())
    stmt = (
        select(FitnessScore, Agent.trade_count, Agent.status)
        .join(Agent, Agent.id == FitnessScore.agent_id)
        .join(latest_fs, (FitnessScore.agent_id == latest_fs.c.agent_id) & (FitnessScore.as_of == latest_fs.c.max_as_of))
    )
    if generation is not None:
        stmt = stmt.where(Agent.generation == generation)
    rows = (await db.execute(stmt)).all()
    if not rows:
        return {"insufficient_data": True, "generation": generation, "components": []}

    contributions: dict[str, list[float]] = defaultdict(list)
    weight_sample: dict = (rows[0][0].weights_used or {})
    for fs, trade_count, status in rows:
        weights = fs.weights_used or {}
        sample_confidence = min(1.0, (trade_count or 0) / _MIN_TRADES_FOR_FULL_CONFIDENCE)
        inactivity_penalty = 1.0 - sample_confidence
        death_penalty = 1.0 if status == AgentStatus.DEAD else 0.0

        for field in _FITNESS_COMPONENT_FIELDS:
            score = getattr(fs, field)
            if score is None:
                continue
            weight = weights.get(_WEIGHT_KEY[field], 0.0)
            contributions[field].append(-weight * score if field in _PENALTY_FIELDS else weight * score)
        contributions["inactivity_penalty"].append(-weights.get(_WEIGHT_KEY["inactivity_penalty"], 0.0) * inactivity_penalty)
        contributions["death_penalty"].append(-weights.get(_WEIGHT_KEY["death_penalty"], 0.0) * death_penalty)

    mean_fitness = float(np.mean([fs.fitness for fs, _, _ in rows]))
    mean_contribution = {k: float(np.mean(v)) for k, v in contributions.items() if v}
    total_abs = sum(abs(v) for v in mean_contribution.values()) or 1.0

    components = [
        {"component": k, "mean_actual_contribution": v, "contribution_pct": abs(v) / total_abs * 100,
         "configured_weight": weight_sample.get(_WEIGHT_KEY.get(k))}
        for k, v in sorted(mean_contribution.items(), key=lambda kv: -abs(kv[1]))
    ]
    return {"insufficient_data": False, "generation": generation, "agent_count": len(rows),
            "mean_fitness": mean_fitness, "components": components}


# --------------------------------------------------------------------------- #
# Phase 13 - champion analysis
# --------------------------------------------------------------------------- #
async def _agent_group_stats(db: AsyncSession, version_ids: list) -> dict:
    if not version_ids:
        return {"count": 0, "avg_trades_per_day": None, "avg_pnl": None, "avg_expectancy": None,
                "avg_drawdown": None, "avg_fitness": None}
    agents = (await db.execute(select(Agent).where(Agent.strategy_version_id.in_(version_ids)))).scalars().all()
    if not agents:
        return {"count": 0, "avg_trades_per_day": None, "avg_pnl": None, "avg_expectancy": None,
                "avg_drawdown": None, "avg_fitness": None}
    agent_ids = [a.id for a in agents]
    trade_rows = (await db.execute(
        select(Trade.agent_id, func.count(), func.coalesce(func.sum(Trade.net_pnl), 0.0))
        .where(Trade.agent_id.in_(agent_ids)).group_by(Trade.agent_id)
    )).all()
    trade_by_agent = {aid: (n, float(pnl)) for aid, n, pnl in trade_rows}

    now = datetime.now(timezone.utc)
    trades_per_day, pnls, expectancies, drawdowns, fitnesses = [], [], [], [], []
    for a in agents:
        n, pnl = trade_by_agent.get(a.id, (0, 0.0))
        trades_per_day.append(n / _agent_age_days(a, now))
        pnls.append(pnl)
        if n:
            expectancies.append(pnl / n)
        drawdowns.append(a.max_drawdown)
        if a.fitness is not None:
            fitnesses.append(a.fitness)
    return {
        "count": len(agents),
        "avg_trades_per_day": float(np.mean(trades_per_day)) if trades_per_day else None,
        "avg_pnl": float(np.mean(pnls)) if pnls else None,
        "avg_expectancy": float(np.mean(expectancies)) if expectancies else None,
        "avg_drawdown": float(np.mean(drawdowns)) if drawdowns else None,
        "avg_fitness": float(np.mean(fitnesses)) if fitnesses else None,
    }


async def get_champions_analysis(db: AsyncSession) -> dict:
    all_versions = (await db.execute(select(StrategyVersion.id, StrategyVersion.champion_status))).all()
    champion_ids = [vid for vid, cs in all_versions if cs == ChampionStatus.CHAMPION]
    non_champion_ids = [vid for vid, cs in all_versions if cs != ChampionStatus.CHAMPION]

    champion_stats = await _agent_group_stats(db, champion_ids)

    profitable_rows = (await db.execute(
        select(Agent.strategy_version_id).where(Agent.realized_pnl > 0).distinct()
    )).scalars().all()
    profitable_version_ids = set(profitable_rows)

    settings = get_settings()
    return {
        "champion_count": len(champion_ids),
        "champion_stats": champion_stats,
        "profitable_not_champion_count": len(profitable_version_ids & set(non_champion_ids)),
        "champion_not_profitable_count": len(set(champion_ids) - profitable_version_ids),
        "promotion_criteria": {
            "min_paper_trade_count": settings.champion_min_paper_trade_count,
            "min_observation_days": settings.champion_min_observation_days,
        },
    }


# --------------------------------------------------------------------------- #
# Phase 11 (reinterpreted) - performance by BACKTEST timeframe, from Experiment records
# (live agents all trade one single global MARKET_TIMEFRAME - see plan Context decision #4)
# --------------------------------------------------------------------------- #
async def get_timeframe_performance(db: AsyncSession) -> dict:
    rows = (await db.execute(
        select(ResearchEpoch.timeframe, Experiment.result)
        .join(ResearchEpoch, ResearchEpoch.epoch_id == Experiment.epoch_id)
        .where(Experiment.status == "COMPLETED")
    )).all()
    if not rows:
        return {"insufficient_data": True, "source": "backtest_experiments", "timeframes": []}

    by_tf: dict[str, list[dict]] = defaultdict(list)
    for tf, result in rows:
        by_tf[tf].append(result or {})

    def _mean(results: list[dict], *keys: str) -> float | None:
        for key in keys:
            vals = [r[key] for r in results if isinstance(r.get(key), (int, float))]
            if vals:
                return float(np.mean(vals))
        return None

    timeframes = [
        {"timeframe": tf, "experiment_count": len(results),
         "avg_pnl": _mean(results, "net_pnl", "pnl"), "avg_expectancy": _mean(results, "expectancy"),
         "avg_profit_factor": _mean(results, "profit_factor"), "avg_win_rate": _mean(results, "win_rate"),
         "avg_max_drawdown": _mean(results, "max_drawdown")}
        for tf, results in sorted(by_tf.items())
    ]
    return {"insufficient_data": False, "source": "backtest_experiments", "timeframes": timeframes}


# --------------------------------------------------------------------------- #
# Phase 16 - ranking stability across time windows (no look-ahead: each window only ever
# reads FitnessScore.as_of <= its own boundary)
# --------------------------------------------------------------------------- #
_STABILITY_WINDOWS = [("1D", 1), ("3D", 3), ("7D", 7), ("14D", 14), ("30D", 30)]
_MIN_AGENTS_FOR_STABILITY = 10


def _spearman(rank_a: dict[str, int], rank_b: dict[str, int]) -> float | None:
    common = set(rank_a) & set(rank_b)
    if len(common) < 3:
        return None
    xs = np.array([rank_a[k] for k in common], dtype=float)
    ys = np.array([rank_b[k] for k in common], dtype=float)
    if xs.std() == 0 or ys.std() == 0:
        return None
    return float(np.corrcoef(xs, ys)[0, 1])


async def _ranking_as_of(db: AsyncSession, boundary: datetime) -> dict[str, int]:
    latest = (select(FitnessScore.agent_id, func.max(FitnessScore.as_of).label("max_as_of"))
              .where(FitnessScore.as_of <= boundary).group_by(FitnessScore.agent_id).subquery())
    rows = (await db.execute(
        select(FitnessScore.agent_id, FitnessScore.fitness)
        .join(latest, (FitnessScore.agent_id == latest.c.agent_id) & (FitnessScore.as_of == latest.c.max_as_of))
    )).all()
    ranked = sorted(rows, key=lambda r: r[1], reverse=True)
    return {str(agent_id): i + 1 for i, (agent_id, _fitness) in enumerate(ranked)}


async def get_ranking_stability(db: AsyncSession) -> dict:
    now = datetime.now(timezone.utc)
    rankings: dict[str, dict[str, int] | None] = {}
    for label, days in _STABILITY_WINDOWS:
        r = await _ranking_as_of(db, now - timedelta(days=days))
        rankings[label] = r if len(r) >= _MIN_AGENTS_FOR_STABILITY else None

    labels = [w[0] for w in _STABILITY_WINDOWS]
    windows_out = []
    for i in range(len(labels) - 1):
        a_label, b_label = labels[i], labels[i + 1]
        a, b = rankings[a_label], rankings[b_label]
        if a is None or b is None:
            windows_out.append({"from": a_label, "to": b_label, "insufficient_history": True})
            continue
        top10_a = {k for k, v in a.items() if v <= 10}
        top10_b = {k for k, v in b.items() if v <= 10}
        top20_a = {k for k, v in a.items() if v <= 20}
        top20_b = {k for k, v in b.items() if v <= 20}
        windows_out.append({
            "from": a_label, "to": b_label, "insufficient_history": False,
            "spearman": _spearman(a, b),
            "top10_overlap": len(top10_a & top10_b) / max(len(top10_a), 1),
            "top20_overlap": len(top20_a & top20_b) / max(len(top20_a), 1),
            "agents_compared": len(set(a) & set(b)),
        })
    return {"windows": windows_out}
