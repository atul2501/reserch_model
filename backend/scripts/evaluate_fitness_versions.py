"""READ-ONLY offline fitness evaluator (research use only). Reconstructs several named fitness
formula/timing versions (app.analytics.fitness_versions.FITNESS_VERSIONS) over a generation's real
trade history and measures how well each version's ranking predicts genuinely FUTURE, strictly-later
realized performance - not just historical PnL correlation. Issues no INSERT/UPDATE/DELETE anywhere;
the session is explicitly rolled back at the end.

Every version protects the sealed OOS holdout identically (see fitness_versions.py's module
docstring) - "v1_timing_fix" only ever moves the evaluation cutoff later, it never bypasses the
OOS-window exclusion.

Limitation, stated honestly: production has one fully-scored generation to date, so this evaluates
across one generation's intra-generation reconstruction grid (many `as_of` points, not many
generations). Re-run this same command once more generations exist - no code changes needed.

Usage:
    python -m scripts.evaluate_fitness_versions --generation 1 --versions v1,v1_timing_fix,v2,v3,v4 \
        --horizons 60,360,1440,4320 --out /tmp/fitness_eval_report.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from sqlalchemy import select

from app.analytics import fitness_forward as ff
from app.analytics.fitness_service import _latest_by_version
from app.analytics.fitness_versions import EVIDENCE_MODE_PRODUCTION, FITNESS_VERSIONS
from app.core.database import AsyncSessionLocal, engine
from app.core.logging import configure_logging, get_logger
from app.models.agent import Agent
from app.models.enums import StrategyStage
from app.models.metrics import FitnessScore
from app.models.research import ResearchEpoch
from app.models.stage_metrics import StageMetrics
from app.models.strategy import Generation
from app.models.trading import Trade

configure_logging()
logger = get_logger(__name__)

GRID_MINUTES_DEFAULT = 60
TOP_KS = (5, 10, 25, 50)
RANDOM_TRIALS = 200


def _spearman(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 3:
        return None, len(pairs)
    a, b = zip(*pairs)
    if len(set(a)) < 2 or len(set(b)) < 2:
        return None, len(pairs)
    ra, rb = pd.Series(a).rank(), pd.Series(b).rank()
    rho = float(ra.corr(rb))
    return (None if rho != rho else rho), len(pairs)


def _pearson(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 3:
        return None, len(pairs)
    a, b = zip(*pairs)
    if len(set(a)) < 2 or len(set(b)) < 2:
        return None, len(pairs)
    return float(np.corrcoef(a, b)[0, 1]), len(pairs)


def _latest_upto(rows, version_id, t):
    """Same pattern as analytics_store.py's internal helper: the most recent row for this
    version with computed_at <= t - so stage evidence never leaks knowledge from after t."""
    latest = None
    for r in rows:
        if r.strategy_version_id == version_id and r.computed_at <= t:
            latest = r
    return latest


async def _load_context(db, generation: int):
    agents = (await db.execute(select(Agent).where(Agent.generation == generation))).scalars().all()
    if not agents:
        raise SystemExit(f"No agents found for generation {generation}")
    agent_ids = [a.id for a in agents]

    trade_rows = (await db.execute(
        select(Trade).where(Trade.agent_id.in_(agent_ids)).order_by(Trade.agent_id, Trade.closed_at)
    )).scalars().all()
    by_agent: dict = defaultdict(list)
    for t in trade_rows:
        by_agent[t.agent_id].append(ff.TradePoint(closed_at=t.closed_at, net_pnl=t.net_pnl,
                                                    notional=t.quantity * t.entry_price, opened_at=t.opened_at))

    epoch = (await db.execute(
        select(ResearchEpoch).where(ResearchEpoch.active.is_(True)).order_by(ResearchEpoch.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    oos_window_ms = (epoch.oos_start_ms, epoch.oos_end_ms) if epoch is not None else None
    if oos_window_ms is None:
        logger.warning("evaluate_fitness_versions.no_active_oos_epoch_found")

    version_ids = {a.strategy_version_id for a in agents}
    backtest_rows = (await db.execute(
        select(StageMetrics).where(StageMetrics.stage == StrategyStage.BACKTEST,
                                    StageMetrics.strategy_version_id.in_(version_ids))
        .order_by(StageMetrics.computed_at)
    )).scalars().all()

    recorded: dict = defaultdict(list)
    for s in (await db.execute(
        select(FitnessScore).where(FitnessScore.agent_id.in_(agent_ids)).order_by(FitnessScore.agent_id, FitnessScore.as_of)
    )).scalars().all():
        recorded[s.agent_id].append(s)

    data_end = max((t.closed_at for t in trade_rows), default=datetime.now(timezone.utc))
    gens = (await db.execute(select(Generation.number, Generation.created_at).order_by(Generation.number))).all()
    rollover = None
    for i, (num, created) in enumerate(gens):
        if num == generation and i + 1 < len(gens):
            rollover = gens[i + 1][1]

    return agents, by_agent, oos_window_ms, backtest_rows, recorded, data_end, rollover


def _grid_as_of_points(by_agent: dict, agents: list, rollover, data_end, grid_minutes: int) -> list[datetime]:
    """Population-wide grid, anchored at the generation's earliest trade - same design choice as
    analytics_store.refresh_fitness_forward, so every point compares the whole cohort that had
    traded by then, not a per-agent-anchored grid that can't be cross-sectionally ranked."""
    all_closes = [p.closed_at for pts in by_agent.values() for p in pts]
    if not all_closes:
        return []
    first_trade = min(all_closes)
    boundary = min(t for t in (rollover, data_end) if t is not None)
    if first_trade >= boundary:
        return []
    span_minutes = (boundary - first_trade).total_seconds() / 60.0
    steps = max(1, int(span_minutes // grid_minutes))
    points = []
    for i in range(1, steps + 1):
        t = first_trade + timedelta(minutes=grid_minutes * i)
        if t >= boundary:
            break
        points.append(t)
    return points


def _stage_evidence_at(backtest_rows, strategy_version_id, t) -> dict:
    bt = _latest_upto(backtest_rows, strategy_version_id, t) if strategy_version_id else None
    return {"oos_score": bt.oos_score if bt is not None else None}


def _reconstruct_snapshot(agent, spec, as_of, points, oos_window_ms, backtest_rows, rollover, data_end) -> dict | None:
    if not any(p.closed_at <= as_of for p in points):
        return None  # no evidence yet at T for this agent: nothing to rank
    facts = ff.AgentFacts(agent_id=agent.id, generation=agent.generation, starting_balance=agent.starting_balance,
                          created_at=agent.created_at, death_timestamp=agent.death_timestamp, status=agent.status)
    stage_evidence = _stage_evidence_at(backtest_rows, agent.strategy_version_id, as_of)
    recon = ff.reconstruct_fitness_at(
        facts, points, as_of=as_of, weights=spec.weights, stage_evidence=stage_evidence,
        oos_window_ms=oos_window_ms, return_transform=spec.return_transform,
    )
    historical_pnl = recon.components["equity_at_t"] - facts.starting_balance
    net_return_pct = historical_pnl / facts.starting_balance if facts.starting_balance else 0.0
    return dict(agent_id=agent.id, as_of=as_of, fitness=recon.fitness, historical_pnl=historical_pnl,
                net_return_pct=net_return_pct, trade_count=recon.components["trade_count"],
                oos_score_raw=stage_evidence["oos_score"], max_drawdown=recon.components["realized_drawdown_pct"],
                return_score=recon.components["return_score"], facts=facts)


def _future_for(agent_id, as_of, horizon, by_agent, facts_by_agent, rollover, data_end):
    facts = facts_by_agent[agent_id]
    window = ff.forward_window(as_of, horizon, death_at=facts.death_timestamp, generation_rollover_at=rollover, data_end=data_end)
    fwd = ff.forward_performance(by_agent.get(agent_id, []), window, starting_balance=facts.starting_balance)
    return fwd, window


def _capture_rate(selected_pnls: list[float], all_pnls_at_snapshot: list[float], k: int) -> float | None:
    best_possible = sum(sorted(all_pnls_at_snapshot, reverse=True)[:k])
    if best_possible == 0:
        return None
    return sum(selected_pnls) / best_possible


def _topk_metrics(snapshots_at_t: list[dict], future_by_agent: dict, k: int) -> dict:
    ranked = sorted(snapshots_at_t, key=lambda s: s["fitness"], reverse=True)[:k]
    all_future_pnls = [future_by_agent[s["agent_id"]].net_pnl or 0.0 for s in snapshots_at_t if future_by_agent[s["agent_id"]].trade_count > 0]
    selected = [s for s in ranked if future_by_agent[s["agent_id"]].trade_count > 0]
    selected_pnls = [future_by_agent[s["agent_id"]].net_pnl or 0.0 for s in selected]
    if not selected_pnls:
        return dict(n=0, capture_rate=None, median_future_pnl=None, mean_future_pnl=None,
                    max_future_drawdown=None, win_rate=None)
    wins = sum(1 for p in selected_pnls if p > 0)
    dds = [future_by_agent[s["agent_id"]].max_drawdown_currency or 0.0 for s in selected]
    return dict(
        n=len(selected_pnls), capture_rate=_capture_rate(selected_pnls, all_future_pnls, k),
        median_future_pnl=statistics.median(selected_pnls), mean_future_pnl=statistics.fmean(selected_pnls),
        max_future_drawdown=min(dds) if dds else None, win_rate=wins / len(selected_pnls),
    )


def _random_baseline(snapshots_at_t: list[dict], future_by_agent: dict, k: int, trials: int) -> dict:
    pool = [s for s in snapshots_at_t if future_by_agent[s["agent_id"]].trade_count > 0]
    if len(pool) < k:
        return dict(mean_future_pnl=None, win_rate=None)
    means, winrates = [], []
    rng = random.Random(20260101)
    for _ in range(trials):
        sample = rng.sample(pool, k)
        pnls = [future_by_agent[s["agent_id"]].net_pnl or 0.0 for s in sample]
        means.append(statistics.fmean(pnls))
        winrates.append(sum(1 for p in pnls if p > 0) / k)
    return dict(mean_future_pnl=statistics.fmean(means), win_rate=statistics.fmean(winrates))


def _pnl_rank_baseline(snapshots_at_t: list[dict], future_by_agent: dict, k: int) -> dict:
    ranked = sorted(snapshots_at_t, key=lambda s: s["historical_pnl"], reverse=True)[:k]
    selected = [s for s in ranked if future_by_agent[s["agent_id"]].trade_count > 0]
    pnls = [future_by_agent[s["agent_id"]].net_pnl or 0.0 for s in selected]
    if not pnls:
        return dict(mean_future_pnl=None, win_rate=None)
    return dict(mean_future_pnl=statistics.fmean(pnls), win_rate=sum(1 for p in pnls if p > 0) / len(pnls))


def _bucket_report(snapshots: list[dict], future_lookup, horizon: int, bucket_fn, bucket_labels) -> dict:
    """`future_lookup(snapshot) -> ForwardPerformance | None` - keyed per (agent_id, as_of), never
    just per agent_id, since one agent contributes many snapshots (one per as_of grid point) and a
    plain agent_id->future dict would silently collide across them."""
    out = {}
    for label in bucket_labels:
        rows = [s for s in snapshots if bucket_fn(s) == label]
        if not rows:
            out[label] = dict(n=0)
            continue
        fitnesses = [r["fitness"] for r in rows]
        pnls = [r["historical_pnl"] for r in rows]
        futs = [fwd.net_pnl for r in rows if (fwd := future_lookup(r)) is not None and fwd.trade_count > 0]
        out[label] = dict(
            n=len(rows), mean_fitness=statistics.fmean(fitnesses), median_fitness=statistics.median(fitnesses),
            mean_historical_pnl=statistics.fmean(pnls), median_historical_pnl=statistics.median(pnls),
            mean_future_pnl=(statistics.fmean(futs) if futs else None),
        )
    return out


def _trade_count_bucket(s: dict) -> str:
    n = s["trade_count"]
    if n == 0:
        return "0"
    if n < 5:
        return "1-4"
    if n < 10:
        return "5-9"
    if n < 30:
        return "10-29"
    return "30+"


def _future_profit_factor(trades, window) -> float | None:
    """Same window filter as ff.forward_performance (window_start exclusive, window_end_actual
    inclusive) - kept separate rather than extending ForwardPerformance, since profit_factor is
    only needed for this one diagnostic, not the top-K/capture-rate machinery."""
    future = [t for t in trades if window.window_start < t.closed_at <= window.window_end_actual]
    if not future:
        return None
    gains = sum(t.net_pnl for t in future if t.net_pnl > 0)
    losses = -sum(t.net_pnl for t in future if t.net_pnl < 0)
    if losses == 0:
        return None  # undefined (no losing trades) rather than a misleading infinity
    return gains / losses


async def _oos_future_analysis(db, generation: int, horizons: list[int], grid_minutes: int) -> dict:
    """Standalone (version-independent) analysis: does StageMetrics.BACKTEST.oos_score - the same
    value that dominates current production fitness (see the prior audit) - actually predict
    FUTURE realized performance, not just historical PnL? oos_score depends only on
    strategy_version_id, not on any fitness formula/weights, so this does its own lightweight pass
    rather than reusing any FITNESS_VERSIONS spec. Reports coverage/censoring stats alongside every
    horizon so results can be judged by how much of the window was actually observable, not just
    the planned horizon."""
    agents, by_agent, oos_window_ms, backtest_rows, recorded, data_end, rollover = await _load_context(db, generation)
    facts_by_agent = {a.id: ff.AgentFacts(agent_id=a.id, generation=a.generation, starting_balance=a.starting_balance,
                                          created_at=a.created_at, death_timestamp=a.death_timestamp, status=a.status)
                       for a in agents}
    as_of_points = _grid_as_of_points(by_agent, agents, rollover, data_end, grid_minutes)
    if not as_of_points:
        return dict(n_as_of_points=0, note="No as_of points available on this generation's data.")

    rows_by_horizon: dict = defaultdict(list)
    coverage_by_horizon: dict = defaultdict(list)
    for agent in agents:
        points = by_agent.get(agent.id, [])
        if not points:
            continue
        for as_of in as_of_points:
            if not any(p.closed_at <= as_of for p in points):
                continue
            oos_score = _stage_evidence_at(backtest_rows, agent.strategy_version_id, as_of)["oos_score"]
            if oos_score is None:
                continue
            for horizon in horizons:
                window = ff.forward_window(as_of, horizon, death_at=agent.death_timestamp,
                                           generation_rollover_at=rollover, data_end=data_end)
                fwd = ff.forward_performance(points, window, starting_balance=agent.starting_balance)
                coverage_by_horizon[horizon].append(dict(coverage=window.window_coverage, censor_reason=window.censor_reason))
                if fwd.trade_count == 0:
                    continue
                pf = _future_profit_factor(points, window)
                rows_by_horizon[horizon].append(dict(
                    oos_score=oos_score, future_pnl=fwd.net_pnl, future_drawdown=fwd.max_drawdown_currency,
                    future_win_rate=fwd.win_rate, future_profit_factor=pf,
                ))

    by_horizon = {}
    for horizon in horizons:
        rows = rows_by_horizon[horizon]
        cov = coverage_by_horizon[horizon]
        mean_coverage = statistics.fmean(c["coverage"] for c in cov) if cov else None
        pct_uncensored = (100 * sum(1 for c in cov if c["censor_reason"] == "none") / len(cov)) if cov else None
        by_horizon[horizon] = dict(
            n_windows=len(cov), n_with_future_trades=len(rows),
            mean_window_coverage=mean_coverage, pct_uncensored_windows=pct_uncensored,
            pearson_oos_vs_future_pnl=_pearson([r["oos_score"] for r in rows], [r["future_pnl"] for r in rows]),
            pearson_oos_vs_future_drawdown=_pearson([r["oos_score"] for r in rows], [r["future_drawdown"] for r in rows]),
            pearson_oos_vs_future_win_rate=_pearson([r["oos_score"] for r in rows], [r["future_win_rate"] for r in rows]),
            pearson_oos_vs_future_profit_factor=_pearson(
                [r["oos_score"] for r in rows if r["future_profit_factor"] is not None],
                [r["future_profit_factor"] for r in rows if r["future_profit_factor"] is not None],
            ),
        )
    return dict(n_as_of_points=len(as_of_points), by_horizon=by_horizon)


async def _evaluate_version(db, version_name: str, generation: int, horizons: list[int], grid_minutes: int) -> dict:
    spec = FITNESS_VERSIONS[version_name]
    agents, by_agent, oos_window_ms, backtest_rows, recorded, data_end, rollover = await _load_context(db, generation)
    facts_by_agent = {a.id: ff.AgentFacts(agent_id=a.id, generation=a.generation, starting_balance=a.starting_balance,
                                          created_at=a.created_at, death_timestamp=a.death_timestamp, status=a.status)
                       for a in agents}

    # ---- which as_of points to evaluate at, per this version's evidence_mode ---- #
    if spec.evidence_mode == EVIDENCE_MODE_PRODUCTION:
        as_of_points = sorted({s.as_of if s.as_of.tzinfo else s.as_of.replace(tzinfo=timezone.utc)
                                for rows in recorded.values() for s in rows})
    else:
        as_of_points = _grid_as_of_points(by_agent, agents, rollover, data_end, grid_minutes)

    if not as_of_points:
        return dict(version=version_name, description=spec.description, n_as_of_points=0,
                    note="No as_of points available for this version on this generation's data.")

    snapshots_by_asof: dict = defaultdict(list)
    for agent in agents:
        points = by_agent.get(agent.id, [])
        for as_of in as_of_points:
            snap = _reconstruct_snapshot(agent, spec, as_of, points, oos_window_ms, backtest_rows, rollover, data_end)
            if snap is not None:
                snapshots_by_asof[as_of].append(snap)

    all_snapshots = [s for snaps in snapshots_by_asof.values() for s in snaps]
    hist_fit = [s["fitness"] for s in all_snapshots]
    hist_pnl = [s["historical_pnl"] for s in all_snapshots]
    rho_hist, n_hist = _spearman(hist_fit, hist_pnl)

    future_cache: dict = {}
    per_horizon: dict = {}
    for horizon in horizons:
        fit_vals, fut_vals = [], []
        topk_out: dict = {k: [] for k in TOP_KS}
        random_out: dict = {k: [] for k in TOP_KS}
        pnlrank_out: dict = {k: [] for k in TOP_KS}
        for as_of, snaps in snapshots_by_asof.items():
            future_by_agent = {}
            for s in snaps:
                key = (s["agent_id"], as_of, horizon)
                if key not in future_cache:
                    future_cache[key] = _future_for(s["agent_id"], as_of, horizon, by_agent, facts_by_agent, rollover, data_end)[0]
                future_by_agent[s["agent_id"]] = future_cache[key]
            for s in snaps:
                fwd = future_by_agent[s["agent_id"]]
                if fwd.trade_count > 0:
                    fit_vals.append(s["fitness"])
                    fut_vals.append(fwd.net_pnl)
            for k in TOP_KS:
                if len(snaps) >= k:
                    topk_out[k].append(_topk_metrics(snaps, future_by_agent, k))
                    random_out[k].append(_random_baseline(snaps, future_by_agent, k, RANDOM_TRIALS))
                    pnlrank_out[k].append(_pnl_rank_baseline(snaps, future_by_agent, k))

        rho_future, n_future = _spearman(fit_vals, fut_vals)

        def _agg(rows, field):
            vals = [r[field] for r in rows if r.get(field) is not None]
            return statistics.fmean(vals) if vals else None

        per_horizon[horizon] = dict(
            spearman_fitness_vs_future_pnl=dict(rho=rho_future, n=n_future),
            topk={k: dict(n_snapshots=len(topk_out[k]),
                          mean_capture_rate=_agg(topk_out[k], "capture_rate"),
                          mean_median_future_pnl=_agg(topk_out[k], "median_future_pnl"),
                          mean_win_rate=_agg(topk_out[k], "win_rate"),
                          random_baseline_mean_future_pnl=_agg(random_out[k], "mean_future_pnl"),
                          random_baseline_win_rate=_agg(random_out[k], "win_rate"),
                          pnl_rank_baseline_mean_future_pnl=_agg(pnlrank_out[k], "mean_future_pnl"),
                          pnl_rank_baseline_win_rate=_agg(pnlrank_out[k], "win_rate"))
                  for k in TOP_KS},
        )

    h0 = horizons[0]
    trade_count_bias = _bucket_report(
        all_snapshots, lambda s: future_cache.get((s["agent_id"], s["as_of"], h0)), h0,
        _trade_count_bucket, ("0", "1-4", "5-9", "10-29", "30+"),
    )

    returns = sorted(s["net_return_pct"] for s in all_snapshots)
    return_distribution = None
    if returns:
        def pct(p):
            idx = min(len(returns) - 1, max(0, int(p * (len(returns) - 1))))
            return returns[idx]
        return_distribution = dict(min=returns[0], p25=pct(0.25), median=pct(0.5), p75=pct(0.75),
                                    p90=pct(0.90), p95=pct(0.95), p99=pct(0.99), max=returns[-1])

    return dict(
        version=version_name, description=spec.description, evidence_mode=spec.evidence_mode,
        n_as_of_points=len(as_of_points), n_snapshots=len(all_snapshots),
        spearman_fitness_vs_historical_pnl=dict(rho=rho_hist, n=n_hist),
        by_horizon=per_horizon, trade_count_bias=trade_count_bias, return_distribution=return_distribution,
    )


async def main(generation: int, versions: list[str], horizons: list[int], grid_minutes: int, out_path: str | None,
              oos_future: bool = True) -> None:
    async with AsyncSessionLocal() as db:
        report: dict = dict(generation=generation, versions={}, generated_at=datetime.now(timezone.utc).isoformat())
        for v in versions:
            if v not in FITNESS_VERSIONS:
                raise SystemExit(f"Unknown version '{v}'. Known: {sorted(FITNESS_VERSIONS)}")
            logger.info("evaluate_fitness_versions.evaluating", version=v)
            report["versions"][v] = await _evaluate_version(db, v, generation, horizons, grid_minutes)
        if oos_future:
            logger.info("evaluate_fitness_versions.oos_future_analysis")
            report["oos_future_analysis"] = await _oos_future_analysis(db, generation, horizons, grid_minutes)
        await db.rollback()  # explicit: read-only by construction, nothing was ever staged to write
    await engine.dispose()

    print(json.dumps(report, indent=2, default=str))
    if out_path:
        with open(out_path, "w") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"\nReport written to {out_path}")
    logger.info("evaluate_fitness_versions.done", generation=generation, versions=versions)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--generation", type=int, required=True)
    ap.add_argument("--versions", default="v1,v1_timing_fix,v2,v3,v4")
    ap.add_argument("--horizons", default="60,360,1440,4320", help="minutes")
    ap.add_argument("--grid-minutes", type=int, default=GRID_MINUTES_DEFAULT)
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-oos-future", action="store_true", help="skip the OOS-score-vs-future-performance analysis")
    args = ap.parse_args()
    asyncio.run(main(
        args.generation, [v.strip() for v in args.versions.split(",")],
        [int(h) for h in args.horizons.split(",")], args.grid_minutes, args.out,
        oos_future=not args.no_oos_future,
    ))
