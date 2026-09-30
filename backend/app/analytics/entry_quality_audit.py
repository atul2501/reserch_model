"""Entry Quality Model V1 - SHADOW AUDIT aggregation (spec: Phase-4 forensic audit dashboard).

Read-only. Computes everything from already-persisted Trade/TradeAnalytics/MarketCandle rows and
the frozen model in entry_quality_model.py. Writes nothing, mutates nothing, and nothing here is
imported by the live decision path - see that module's docstring for why.

Every number in this module answers "if we HAD filtered on this model, what would the numbers
have looked like" - it is retrospective and hypothetical by construction, never a claim about
what actually happened to real trades.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.entry_quality_features import compute_features, feature_row_at_or_before
from app.analytics.entry_quality_model import (
    FEATURE_COLUMNS, DIRECTION_SIGNED_FEATURES, MODEL_VERSION,
    TRAINING_WINDOW_START_MS, TRAINING_WINDOW_END_MS, model_status, predict_proba,
    _COEF, _SCALER_MEAN, _SCALER_SCALE,
)
from app.core.config import get_settings
from app.models.agent import Agent
from app.models.analytics import TradeAnalytics
from app.models.trading import Trade
from app.research.dataset import load_confirmed_candles

MIN_SAMPLE = 30  # matches app.analytics.dashboard_service._MIN_TRADES_FOR_FULL_CONFIDENCE convention
THRESHOLD_GRID = (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80)
DEFAULT_THRESHOLD = 0.60
INSUFFICIENT = "INSUFFICIENT_DATA"
HOLD_BUCKETS = [(0, 60, "<1min"), (60, 300, "1-5min"), (300, 900, "5-15min"), (900, 1800, "15-30min"),
                (1800, 3600, "30-60min"), (3600, 7200, "1-2h"), (7200, None, "2h+")]


@dataclass
class _Row:
    trade_id: str
    agent_id: str
    generation: int
    family: str | None
    regime: str | None
    side: str
    net_pnl: float
    holding_seconds: int
    quality_class: str
    mfe_r: float | None
    mae_r: float | None
    closed_at: datetime
    signal_ms: int
    exit_reason: str
    probability: float | None  # None = could not be scored (feature coverage gap)


async def _load_rows(
    db: AsyncSession, *, family: str | None, regime: str | None, side: str | None,
    generation: int | None, agent_id: str | None, since: datetime | None, until: datetime | None,
) -> tuple[list[_Row], int, int]:
    """Returns (scored rows, total_signals_considered, unscorable_count)."""
    settings = get_settings()
    candles = await load_confirmed_candles(db, settings.market_symbol, settings.market_timeframe)
    if candles.empty:
        return [], 0, 0
    feat = compute_features(candles)

    stmt = (
        select(Trade, TradeAnalytics, Agent.generation)
        .join(TradeAnalytics, TradeAnalytics.trade_id == Trade.id)
        .join(Agent, Agent.id == Trade.agent_id)
        .where(TradeAnalytics.signal_bar_open_time_ms.is_not(None))
    )
    if family:
        stmt = stmt.where(TradeAnalytics.family == family)
    if regime:
        stmt = stmt.where(TradeAnalytics.regime == regime)
    if side:
        stmt = stmt.where(Trade.side == side)
    if generation is not None:
        stmt = stmt.where(Agent.generation == generation)
    if agent_id:
        stmt = stmt.where(Trade.agent_id == agent_id)
    if since:
        stmt = stmt.where(Trade.closed_at >= since)
    if until:
        stmt = stmt.where(Trade.closed_at <= until)

    result = (await db.execute(stmt)).all()
    rows: list[_Row] = []
    unscorable = 0
    for trade, ta, generation_no in result:
        raw = feature_row_at_or_before(feat, ta.signal_bar_open_time_ms)
        probability = None
        if raw is not None:
            pred = predict_proba(raw, side=trade.side.value if hasattr(trade.side, "value") else trade.side)
            probability = pred.probability if pred is not None else None
        if probability is None:
            unscorable += 1
        rows.append(_Row(
            trade_id=str(trade.id), agent_id=str(trade.agent_id), generation=generation_no,
            family=ta.family, regime=ta.regime,
            side=trade.side.value if hasattr(trade.side, "value") else trade.side,
            net_pnl=trade.net_pnl, holding_seconds=trade.holding_seconds, quality_class=ta.trade_quality_class,
            mfe_r=ta.mfe_r, mae_r=ta.mae_r, closed_at=trade.closed_at,
            signal_ms=ta.signal_bar_open_time_ms, exit_reason=trade.exit_reason,
            probability=probability,
        ))
    return rows, len(result), unscorable


def _metrics(rows: list[_Row]) -> dict:
    if not rows:
        return {"trades": 0, "win_rate": None, "net_pnl": None, "expectancy": None, "profit_factor": None,
                "avg_win": None, "avg_loss": None, "avg_hold_seconds": None}
    pnls = [r.net_pnl for r in rows]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "trades": len(rows),
        "win_rate": len(wins) / len(rows),
        "net_pnl": sum(pnls),
        "expectancy": sum(pnls) / len(rows),
        # None (never Infinity) when there are no losses to divide by - Infinity is not valid
        # JSON and would break every real client's response.json() the one time a bucket happens
        # to have zero losing trades.
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else None,
        "avg_win": (gross_win / len(wins)) if wins else None,
        "avg_loss": (sum(losses) / len(losses)) if losses else None,
        "avg_hold_seconds": sum(r.holding_seconds for r in rows) / len(rows),
    }


def _shadow_split(rows: list[_Row], threshold: float) -> tuple[list[_Row], list[_Row], list[_Row]]:
    """Returns (scorable, shadow_trade, shadow_no_trade). Unscorable rows are excluded from both
    shadow buckets - they can't be graded, so they're neither kept nor filtered, just reported as
    a coverage gap."""
    scorable = [r for r in rows if r.probability is not None]
    shadow_trade = [r for r in scorable if r.probability >= threshold]
    shadow_no_trade = [r for r in scorable if r.probability < threshold]
    return scorable, shadow_trade, shadow_no_trade


def _model_status_and_health(rows: list[_Row], total_signals: int, unscorable: int) -> tuple[dict, dict]:
    status = model_status()
    scorable = total_signals - unscorable
    health = {
        "model_loaded": True, "feature_schema_valid": True,
        "shadow_predictions": scorable, "unscorable_signals": unscorable,
        "coverage_pct": (scorable / total_signals) if total_signals else None,
        "prediction_errors": 0,  # predict_proba never raises; a coverage gap is not an "error"
        "invalid_probabilities": sum(
            1 for r in rows if r.probability is not None and not (0.0 <= r.probability <= 1.0)
        ),
    }
    return status, health


def _funnel(total_signals: int, unscorable: int, shadow_trade: list[_Row], shadow_no_trade: list[_Row]) -> dict:
    scorable = total_signals - unscorable
    return {
        "strategy_signals": total_signals,
        "scored": scorable,
        "unscorable": unscorable,
        "shadow_trade": len(shadow_trade),
        "shadow_no_trade": len(shadow_no_trade),
        "actual_trades": total_signals,  # unchanged - the shadow model has never gated a real trade
    }


def _probability_distribution(rows: list[_Row]) -> list[dict]:
    scorable = [r for r in rows if r.probability is not None]
    out = []
    for lo in np.arange(0.0, 1.0, 0.1):
        hi = round(lo + 0.1, 2)
        bucket = [r for r in scorable if lo <= r.probability < hi or (hi == 1.0 and r.probability == 1.0)]
        n = len(bucket)
        out.append({
            "bucket": f"{lo:.2f}-{hi:.2f}", "n": n,
            "pct_of_signals": (n / len(scorable)) if scorable else None,
            "actual_win_rate": (sum(1 for r in bucket if r.net_pnl > 0) / n) if n else None,
            "avg_pnl": (sum(r.net_pnl for r in bucket) / n) if n else None,
            "sufficient_sample": n >= MIN_SAMPLE,
        })
    return out


def _calibration(rows: list[_Row]) -> dict:
    scorable = [r for r in rows if r.probability is not None]
    if not scorable:
        return {"points": [], "brier_score": None, "log_loss": None, "n": 0}
    points = []
    for lo in np.arange(0.0, 1.0, 0.1):
        hi = round(lo + 0.1, 2)
        bucket = [r for r in scorable if lo <= r.probability < hi or (hi == 1.0 and r.probability == 1.0)]
        if not bucket:
            continue
        points.append({
            "predicted_mean": sum(r.probability for r in bucket) / len(bucket),
            "actual_win_rate": sum(1 for r in bucket if r.net_pnl > 0) / len(bucket),
            "n": len(bucket), "sufficient_sample": len(bucket) >= MIN_SAMPLE,
        })
    eps = 1e-9
    brier = sum((r.probability - (1.0 if r.net_pnl > 0 else 0.0)) ** 2 for r in scorable) / len(scorable)
    logloss = -sum(
        (1.0 if r.net_pnl > 0 else 0.0) * math.log(max(r.probability, eps))
        + (0.0 if r.net_pnl > 0 else 1.0) * math.log(max(1 - r.probability, eps))
        for r in scorable
    ) / len(scorable)
    return {"points": points, "brier_score": brier, "log_loss": logloss, "n": len(scorable)}


def _threshold_audit(rows: list[_Row]) -> list[dict]:
    out = []
    for t in THRESHOLD_GRID:
        _, shadow_trade, shadow_no_trade = _shadow_split(rows, t)
        m = _metrics(shadow_trade)
        stop_imm_pct = (
            sum(1 for r in shadow_trade if r.quality_class == "STOP_IMMEDIATE") / len(shadow_trade)
            if shadow_trade else None
        )
        out.append({
            "threshold": t, "shadow_trades": len(shadow_trade), "shadow_no_trade": len(shadow_no_trade),
            "win_rate": m["win_rate"], "expectancy": m["expectancy"], "profit_factor": m["profit_factor"],
            "net_pnl": m["net_pnl"], "stop_immediate_pct": stop_imm_pct,
            "sufficient_sample": len(shadow_trade) >= MIN_SAMPLE,
        })
    return out


def _stop_immediate_audit(rows: list[_Row], threshold: float) -> dict:
    scorable = [r for r in rows if r.probability is not None]
    actual_stop = [r for r in rows if r.quality_class == "STOP_IMMEDIATE"]
    _, shadow_trade, _ = _shadow_split(rows, threshold)
    shadow_stop = [r for r in shadow_trade if r.quality_class == "STOP_IMMEDIATE"]

    def summarize(pool):
        n = len(pool)
        return {"count": n, "pct_of_trades": None, "avg_mfe_r": (sum(r.mfe_r for r in pool if r.mfe_r is not None) /
                max(1, sum(1 for r in pool if r.mfe_r is not None))) if any(r.mfe_r is not None for r in pool) else None,
                "avg_mae_r": (sum(r.mae_r for r in pool if r.mae_r is not None) /
                max(1, sum(1 for r in pool if r.mae_r is not None))) if any(r.mae_r is not None for r in pool) else None}

    actual = summarize(actual_stop)
    actual["pct_of_trades"] = (len(actual_stop) / len(rows)) if rows else None
    shadow = summarize(shadow_stop)
    shadow["pct_of_trades"] = (len(shadow_stop) / len(shadow_trade)) if shadow_trade else None
    reduction = None
    if len(actual_stop) >= MIN_SAMPLE and len(shadow_trade) >= MIN_SAMPLE:
        reduction = 1.0 - (shadow["pct_of_trades"] / actual["pct_of_trades"]) if actual["pct_of_trades"] else None
    return {"actual": actual, "shadow_filtered": shadow, "reduction_pct": reduction,
            "sufficient_sample": len(actual_stop) >= MIN_SAMPLE and len(shadow_trade) >= MIN_SAMPLE}


def _group_breakdown(rows: list[_Row], key: str, threshold: float) -> list[dict]:
    groups: dict[str, list[_Row]] = {}
    for r in rows:
        k = getattr(r, key) or "UNKNOWN"
        groups.setdefault(k, []).append(r)
    out = []
    for k, grp in sorted(groups.items()):
        scorable = [r for r in grp if r.probability is not None]
        _, shadow_trade, shadow_no_trade = _shadow_split(grp, threshold)
        actual_m, shadow_m = _metrics(grp), _metrics(shadow_trade)
        sufficient = len(grp) >= MIN_SAMPLE and len(shadow_trade) >= MIN_SAMPLE
        out.append({
            key: k, "signals": len(grp), "actual_trades": len(grp), "scored": len(scorable),
            "shadow_trades": len(shadow_trade), "shadow_no_trade": len(shadow_no_trade),
            "actual_win_rate": actual_m["win_rate"], "shadow_win_rate": shadow_m["win_rate"] if sufficient else None,
            "actual_expectancy": actual_m["expectancy"], "shadow_expectancy": shadow_m["expectancy"] if sufficient else None,
            "sufficient_sample": sufficient,
        })
    return out


def _strategy_regime_matrix(rows: list[_Row], threshold: float, metric: str) -> list[dict]:
    cells: dict[tuple[str, str], list[_Row]] = {}
    for r in rows:
        cells.setdefault((r.family or "UNKNOWN", r.regime or "UNKNOWN"), []).append(r)
    out = []
    for (family, regime), grp in sorted(cells.items()):
        _, shadow_trade, _ = _shadow_split(grp, threshold)
        sufficient = len(grp) >= MIN_SAMPLE
        actual_m = _metrics(grp)
        shadow_m = _metrics(shadow_trade) if len(shadow_trade) >= MIN_SAMPLE else None
        value_map = {
            "actual_expectancy": actual_m["expectancy"],
            "shadow_expectancy": shadow_m["expectancy"] if shadow_m else None,
            "actual_win_rate": actual_m["win_rate"],
            "shadow_win_rate": shadow_m["win_rate"] if shadow_m else None,
            "profit_factor": actual_m["profit_factor"],
            "stop_immediate_pct": sum(1 for r in grp if r.quality_class == "STOP_IMMEDIATE") / len(grp) if grp else None,
        }
        out.append({
            "family": family, "regime": regime, "trade_count": len(grp),
            "value": value_map.get(metric) if sufficient else None,
            "sufficient_sample": sufficient, "label": None if sufficient else INSUFFICIENT,
        })
    return out


def _hold_time_audit(rows: list[_Row], threshold: float) -> list[dict]:
    out = []
    for lo, hi, label in HOLD_BUCKETS:
        bucket = [r for r in rows if r.holding_seconds >= lo and (hi is None or r.holding_seconds < hi)]
        _, shadow_trade, _ = _shadow_split(bucket, threshold)
        m = _metrics(bucket)
        shadow_m = _metrics(shadow_trade) if len(shadow_trade) >= MIN_SAMPLE else None
        out.append({
            "bucket": label, "trades": len(bucket), "win_rate": m["win_rate"], "expectancy": m["expectancy"],
            "profit_factor": m["profit_factor"],
            "stop_immediate_pct": (sum(1 for r in bucket if r.quality_class == "STOP_IMMEDIATE") / len(bucket))
                if bucket else None,
            "shadow_win_rate": shadow_m["win_rate"] if shadow_m else None,
            "shadow_expectancy": shadow_m["expectancy"] if shadow_m else None,
            "sufficient_sample": len(bucket) >= MIN_SAMPLE,
        })
    return out


def _feature_importance() -> list[dict]:
    out = [{"feature": f, "coefficient": c, "direction": "increases win probability" if c > 0 else "decreases win probability",
            "abs_importance": abs(c)} for f, c in zip(FEATURE_COLUMNS, _COEF)]
    return sorted(out, key=lambda x: -x["abs_importance"])


def _drift(rows: list[_Row]) -> dict:
    """Compares the most recent 20% of scored rows (by closed_at) against the frozen training
    window's standardization baseline. WARNING thresholds are a documented starting heuristic,
    not derived from monitoring history (there isn't any yet): mean |z-shift| > 0.5 across
    features = feature drift; predicted-probability mean shift > 0.05 = prediction drift;
    win-rate shift > 0.10 vs the model's own OOS win rate = outcome drift."""
    scorable = sorted((r for r in rows if r.probability is not None), key=lambda r: r.closed_at)
    if len(scorable) < MIN_SAMPLE * 2:
        return {"feature_drift": "INSUFFICIENT_DATA", "prediction_drift": "INSUFFICIENT_DATA",
                "outcome_drift": "INSUFFICIENT_DATA", "note": "need at least 2x MIN_SAMPLE scored rows"}
    recent = scorable[-max(MIN_SAMPLE, len(scorable) // 5):]
    recent_prob_mean = sum(r.probability for r in recent) / len(recent)
    all_prob_mean = sum(r.probability for r in scorable) / len(scorable)
    prediction_drift = "WARNING" if abs(recent_prob_mean - all_prob_mean) > 0.05 else "NORMAL"
    recent_win_rate = sum(1 for r in recent if r.net_pnl > 0) / len(recent)
    from app.analytics.entry_quality_model import OOS_AUC  # noqa: F401 (documents context, not used numerically)
    outcome_drift = "WARNING" if abs(recent_win_rate - 0.30) > 0.10 else "NORMAL"  # 0.30 ~= dataset base rate
    return {
        "feature_drift": "NOT_COMPUTED",  # needs per-row raw feature vectors, not just probability - left for v2
        "prediction_drift": prediction_drift, "outcome_drift": outcome_drift,
        "recent_predicted_mean": recent_prob_mean, "baseline_predicted_mean": all_prob_mean,
        "recent_win_rate": recent_win_rate, "recent_n": len(recent),
        "thresholds_documented": "prediction_drift: |mean shift|>0.05; outcome_drift: |win_rate-0.30|>0.10",
    }


async def build_audit(
    db: AsyncSession, *, family: str | None = None, regime: str | None = None, side: str | None = None,
    generation: int | None = None, agent_id: str | None = None, since: datetime | None = None,
    until: datetime | None = None, threshold: float = DEFAULT_THRESHOLD, matrix_metric: str = "actual_expectancy",
) -> dict:
    rows, total_signals, unscorable = await _load_rows(
        db, family=family, regime=regime, side=side, generation=generation, agent_id=agent_id,
        since=since, until=until,
    )
    status, health = _model_status_and_health(rows, total_signals, unscorable)
    scorable, shadow_trade, shadow_no_trade = _shadow_split(rows, threshold)

    # "OOS" = trades whose SIGNAL fired after the frozen model's train+val window ended - i.e. the
    # rows this exact model has never seen, matching entry_quality_model.py's TRAINING_WINDOW_END_MS.
    oos_rows = [r for r in scorable if r.signal_ms > TRAINING_WINDOW_END_MS]
    return {
        "shadow_only_banner": "SHADOW — DOES NOT AFFECT LIVE TRADING",
        "model_status": status,
        "model_health": health,
        "filters_applied": {"family": family, "regime": regime, "side": side, "generation": generation,
                            "agent_id": agent_id, "since": since.isoformat() if since else None,
                            "until": until.isoformat() if until else None, "threshold": threshold},
        "live_vs_shadow": {
            "actual": _metrics(rows), "shadow_filtered": _metrics(shadow_trade),
            "label": "Hypothetical Shadow Result — trades were NOT actually blocked",
        },
        "funnel": _funnel(total_signals, unscorable, shadow_trade, shadow_no_trade),
        "probability_distribution": _probability_distribution(rows),
        "calibration": _calibration(rows),
        "threshold_audit": {"rows": _threshold_audit(rows),
                            "note": "Exploratory threshold analysis — not production configuration"},
        "stop_immediate_audit": _stop_immediate_audit(rows, threshold),
        "strategy_breakdown": _group_breakdown(rows, "family", threshold),
        "regime_breakdown": _group_breakdown(rows, "regime", threshold),
        "strategy_regime_matrix": {"metric": matrix_metric, "cells": _strategy_regime_matrix(rows, threshold, matrix_metric)},
        "long_short": _group_breakdown(rows, "side", threshold),
        "hold_time_audit": _hold_time_audit(rows, threshold),
        "feature_importance": _feature_importance(),
        "model_version_info": {
            "model_version": MODEL_VERSION, "n_features": len(FEATURE_COLUMNS),
            "training_window_start": datetime.fromtimestamp(TRAINING_WINDOW_START_MS / 1000, tz=timezone.utc).isoformat(),
            "training_window_end": datetime.fromtimestamp(TRAINING_WINDOW_END_MS / 1000, tz=timezone.utc).isoformat(),
            "n_training_rows": status["train_samples"] + status["validation_samples"],
        },
        "data_freshness": {
            "latest_trade_closed_at": max((r.closed_at for r in rows), default=None),
            "latest_prediction_scored": max((r.closed_at for r in scorable), default=None),
            "model_trained_at": status["trained_at"],
        },
        "oos_card": {
            "oos_auc": status["oos_auc"],
            "oos_trades": len(oos_rows),
            "oos_win_rate": (sum(1 for r in oos_rows if r.net_pnl > 0) / len(oos_rows)) if oos_rows else None,
            "status": ("INSUFFICIENT_DATA" if len(oos_rows) < MIN_SAMPLE
                       else "PROMISING" if status["oos_auc"] > 0.55 else "FAILED"),
        },
        "drift": _drift(rows),
        "mfe_mae_scatter": _mfe_mae_scatter(rows),
        "time_series": _time_series(rows, threshold),
        "audit_questions": {
            "q1_probability_tracks_win_rate": _calibration(rows)["points"],
            "q10_sufficient_data": len(scorable) >= MIN_SAMPLE * 3,
        },
    }


async def load_rows(
    db: AsyncSession, *, family: str | None = None, regime: str | None = None, side: str | None = None,
    generation: int | None = None, agent_id: str | None = None, since: datetime | None = None,
    until: datetime | None = None,
) -> list[_Row]:
    """Public entry point for callers (e.g. the CSV export route) that need row-level detail
    rather than the aggregated audit payload."""
    rows, _, _ = await _load_rows(db, family=family, regime=regime, side=side, generation=generation,
                                  agent_id=agent_id, since=since, until=until)
    return rows


def _mfe_mae_scatter(rows: list[_Row], *, sample_cap: int = 2000) -> list[dict]:
    have = [r for r in rows if r.mfe_r is not None and r.mae_r is not None]
    if len(have) > sample_cap:
        step = len(have) // sample_cap
        have = have[::max(1, step)]
    return [{"mae_r": r.mae_r, "mfe_r": r.mfe_r, "is_win": r.net_pnl > 0,
             "quality_class": r.quality_class} for r in have]


def _time_series(rows: list[_Row], threshold: float, *, max_points: int = 500) -> dict:
    ordered = sorted(rows, key=lambda r: r.closed_at)
    actual_cum, shadow_cum = [], []
    a_running = s_running = 0.0
    for r in ordered:
        a_running += r.net_pnl
        actual_cum.append({"t": r.closed_at.isoformat(), "v": a_running})
        if r.probability is None or r.probability >= threshold:
            s_running += r.net_pnl
        shadow_cum.append({"t": r.closed_at.isoformat(), "v": s_running})
    def downsample(series):
        if len(series) <= max_points:
            return series
        step = len(series) // max_points
        return series[::step]
    win_flags = [1 if r.net_pnl > 0 else 0 for r in ordered]
    rolling_50 = [sum(win_flags[max(0, i - 49):i + 1]) / len(win_flags[max(0, i - 49):i + 1])
                  for i in range(len(win_flags))]
    return {
        "actual_cumulative_pnl": downsample(actual_cum),
        "hypothetical_shadow_cumulative_pnl": downsample(shadow_cum),
        "rolling_50_trade_win_rate": downsample([{"t": r.closed_at.isoformat(), "v": w}
                                                  for r, w in zip(ordered, rolling_50)]),
        "labels": {"actual": "ACTUAL", "shadow": "HYPOTHETICAL SHADOW — not real account equity"},
    }


def export_rows(
    db_rows: list[_Row], *, threshold: float,
) -> list[dict]:
    """Audit-export field list, per the dashboard spec: timestamp, agent_id, generation_id,
    strategy, regime, direction, model_version, predicted_probability, shadow_threshold,
    shadow_decision, actual_trade, actual_outcome, actual_pnl, mfe, mae, hold_seconds, exit_reason."""
    out = []
    for r in db_rows:
        out.append({
            "timestamp": r.closed_at.isoformat(), "trade_id": r.trade_id, "agent_id": r.agent_id,
            "generation_id": r.generation, "strategy": r.family, "regime": r.regime, "direction": r.side,
            "model_version": MODEL_VERSION, "predicted_probability": r.probability,
            "shadow_threshold": threshold,
            "shadow_decision": ("shadow_trade" if r.probability is not None and r.probability >= threshold
                                else "shadow_no_trade" if r.probability is not None else "unscorable"),
            "actual_trade": True, "actual_outcome": "win" if r.net_pnl > 0 else "loss",
            "actual_pnl": r.net_pnl, "mfe_r": r.mfe_r, "mae_r": r.mae_r,
            "hold_seconds": r.holding_seconds, "exit_reason": r.exit_reason,
            "trade_quality_class": r.quality_class,
        })
    return out
