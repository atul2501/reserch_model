"""Reusable baseline-vs-candidate experiment runner (spec: multi-week readiness
phase 2). Generalizes the pattern `scripts/compare_fitness_correction.py`
already proved out (re-run `evaluate_in_sample` against the SAME epoch/frame a
real research cycle would use) into a named, persisted, non-overwriting
experiment with full provenance, using the existing registry
(`app.research.registry.register_experiment`/`finish_experiment`).

Design decision, stated explicitly because it's easy to get wrong: this runner
NEVER touches the sealed final-OOS slice (`app.research.lockbox.evaluate_oos_once`).
That evaluation is rate-limited to once per (strategy_version, dataset) and once
per lineage per epoch — spending it on an exploratory baseline-vs-candidate run
would burn the one real OOS check a promotion-track strategy gets, defeating the
whole point of the lockbox. Every result from this runner is therefore an
IN-SAMPLE (train+validation) result; the `oos` field on `ExperimentMetrics`
always explains that the protected holdout was deliberately not spent, not that
data was insufficient.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import trade_quality as tq
from app.backtesting.data import prepare_backtest_data
from app.backtesting.engine import BacktestResult, BacktestTrade
from app.evolution.rng import derive_seed
from app.models.research import Experiment, ResearchEpoch
from app.research import dataset as ds
from app.research.evaluation import evaluate_in_sample
from app.research.lockbox import FULL_CONFIDENCE_TRADES
from app.research.registry import finish_experiment, register_experiment
from app.schemas.strategy_dna import StrategyDNA
from app.strategies.engine import dna_indicator_specs

OOS_NOTE = ("NOT EVALUATED — the protected final-OOS holdout is rate-limited (one evaluation "
            "per strategy version, and per lineage, per epoch) and reserved for promotion-track "
            "candidates; a generic experiment runner must never spend it on exploratory runs.")


@dataclass
class ExperimentMetrics:
    net_pnl: float
    expectancy: float | None
    max_drawdown_pct: float
    win_rate: float | None
    profit_factor: float | None
    trade_count: int
    average_r: float | None
    average_r_note: str
    mfe_capture: float | None
    agent_survival: float          # 1.0 if the run's equity never hit its death condition, else 0.0
    sample_label: str              # "IN-SAMPLE" or "PROMISING — REQUIRES UNSEEN DATA" (trade_count < FULL_CONFIDENCE_TRADES)
    oos: str = OOS_NOTE


def _bars_from_frame(frame: pd.DataFrame, lo: int, hi: int) -> list[tq.Bar]:
    sl = frame.iloc[max(0, lo): hi + 1]
    return [tq.Bar(open_time=int(r.open_time), open=float(r.open), high=float(r.high), low=float(r.low), close=float(r.close))
            for r in sl.itertuples()]


def _stop_loss_price(dna: StrategyDNA, trade: BacktestTrade) -> float | None:
    """Only computable without replaying per-bar indicator context (ATR/swing levels,
    which BacktestTrade does not retain) when the DNA's stop method is a fixed percentage
    of entry price. atr_multiple/structure_based stops are honestly left unpriced here —
    see ExperimentMetrics.average_r_note."""
    if not dna.stop_loss.enabled or dna.stop_loss.method != "fixed_pct":
        return None
    pct = dna.stop_loss.value / 100.0
    long = trade.side.value.upper() != "SHORT" if hasattr(trade.side, "value") else str(trade.side).upper() != "SHORT"
    return trade.entry_price * (1 - pct) if long else trade.entry_price * (1 + pct)


def compute_metrics(result: BacktestResult, frame: pd.DataFrame, dna: StrategyDNA) -> ExperimentMetrics:
    trades = result.trades
    net_pnl = sum(t.net_pnl for t in trades)
    trade_count = len(trades)

    r_values: list[float] = []
    mfe_capture_values: list[float] = []
    stop_method = dna.stop_loss.method if dna.stop_loss.enabled else None
    for t in trades:
        long = str(t.side).upper().endswith("LONG")
        stop_price = _stop_loss_price(dna, t)
        facts = tq.TradeFacts(
            side="LONG" if long else "SHORT", entry_price=t.entry_price, exit_price=t.exit_price,
            quantity=t.quantity, opened_at_ms=int(frame.iloc[t.entry_index].open_time),
            closed_at_ms=int(frame.iloc[t.exit_index].open_time),
            stop_loss_price=stop_price, take_profit_price=None,
            persisted_peak_price=None, persisted_trough_price=None,
            entry_bar_open_ms=int(frame.iloc[t.entry_index].open_time), exit_reason=t.exit_reason,
        )
        bars = _bars_from_frame(frame, t.entry_index, min(t.exit_index + tq.POST_EXIT_BARS + 1, len(frame) - 1))
        bar_ms = int(frame.iloc[1].open_time - frame.iloc[0].open_time) if len(frame) > 1 else 60_000
        ex = tq.analyze_trade(facts, bars, bar_ms)
        if ex.mfe_r is not None:
            r_values.append(t.net_pnl / (stop_price and abs(t.entry_price - stop_price) * t.quantity) if stop_price else ex.mfe_r)
        if ex.max_unrealized_profit and ex.max_unrealized_profit > 0:
            mfe_capture_values.append(t.net_pnl / ex.max_unrealized_profit)

    average_r = sum(r_values) / len(r_values) if r_values else None
    if trade_count == 0:
        average_r_note = "n/a: no trades"
    elif stop_method != "fixed_pct":
        average_r_note = f"n/a: stop method is {stop_method!r}, not 'fixed_pct' (needs per-bar ATR/structure context BacktestTrade doesn't retain)"
    else:
        average_r_note = "computed from the DNA's fixed_pct stop distance"

    sample_label = "IN-SAMPLE" if trade_count >= FULL_CONFIDENCE_TRADES else "PROMISING — REQUIRES UNSEEN DATA"

    return ExperimentMetrics(
        net_pnl=net_pnl, expectancy=result.expectancy, max_drawdown_pct=result.max_drawdown_pct,
        win_rate=result.win_rate, profit_factor=result.profit_factor, trade_count=trade_count,
        average_r=average_r, average_r_note=average_r_note,
        mfe_capture=(sum(mfe_capture_values) / len(mfe_capture_values)) if mfe_capture_values else None,
        agent_survival=0.0 if result.dead else 1.0, sample_label=sample_label,
    )


@dataclass
class RunOutcome:
    experiment: Experiment
    metrics: ExperimentMetrics
    trade_count: int


async def run_baseline_vs_candidate(
    db: AsyncSession, *, baseline_dna: StrategyDNA, candidate_dna: StrategyDNA, name: str,
) -> tuple[RunOutcome, RunOutcome]:
    """Runs both DNAs against the SAME active epoch's train+validation frame (never the
    sealed OOS slice), persists a real, non-overwriting Experiment row for each (new
    experiment_id every call — nothing is ever updated in place), and returns their
    (Experiment, ExperimentMetrics) pairs."""
    epoch = await ds.get_active_epoch(db, "SOL", "1m")
    if epoch is None:
        raise ValueError("no active ResearchEpoch — run the research pipeline at least once first")
    full_candles = await ds.load_epoch_candles(db, epoch)
    frame = ds.slice_train_validation(full_candles, epoch)

    outcomes = []
    for label, dna in (("baseline", baseline_dna), ("candidate", candidate_dna)):
        seed = derive_seed(f"experiment:{name}", epoch.epoch_id, label)
        exp = await register_experiment(
            db, kind="evaluation", seed=seed, epoch=epoch,
            parameters={"name": name, "role": label, "dna": dna.model_dump(mode="json")},
        )
        data = prepare_backtest_data(frame, symbol=epoch.symbol, timeframe=epoch.timeframe, specs=dna_indicator_specs(dna))
        ev = evaluate_in_sample(uuid.uuid4(), dna, frame, data, epoch)
        combined = BacktestResult(
            equity_curve=ev.train.equity_curve + ev.validation.equity_curve,
            trades=ev.train.trades + ev.validation.trades,
            final_equity=ev.validation.final_equity, starting_equity=ev.train.starting_equity,
            dead=ev.train.dead or ev.validation.dead,
        )
        metrics = compute_metrics(combined, frame, dna)
        await finish_experiment(db, exp, status="COMPLETED", result={
            "net_pnl": metrics.net_pnl, "expectancy": metrics.expectancy, "max_drawdown_pct": metrics.max_drawdown_pct,
            "win_rate": metrics.win_rate, "profit_factor": metrics.profit_factor, "trade_count": metrics.trade_count,
            "average_r": metrics.average_r, "average_r_note": metrics.average_r_note,
            "mfe_capture": metrics.mfe_capture, "agent_survival": metrics.agent_survival,
            "sample_label": metrics.sample_label, "oos": metrics.oos, "validation_score": ev.validation_score,
        })
        outcomes.append(RunOutcome(experiment=exp, metrics=metrics, trade_count=metrics.trade_count))

    return outcomes[0], outcomes[1]


def render_comparison(name: str, baseline: RunOutcome, candidate: RunOutcome) -> str:
    b, c = baseline.metrics, candidate.metrics
    rows = [
        ("Net P&L", b.net_pnl, c.net_pnl),
        ("Expectancy", b.expectancy, c.expectancy),
        ("Max Drawdown", b.max_drawdown_pct, c.max_drawdown_pct),
        ("Win Rate", b.win_rate, c.win_rate),
        ("Average R", b.average_r, c.average_r),
        ("MFE Capture", b.mfe_capture, c.mfe_capture),
        ("Trade Count", b.trade_count, c.trade_count),
        ("Agent Survival", b.agent_survival, c.agent_survival),
        ("Profit Factor", b.profit_factor, c.profit_factor),
    ]
    lines = [f"experiment: {name}", f"baseline={baseline.experiment.experiment_id}  candidate={candidate.experiment.experiment_id}", ""]
    lines.append(f"{'Metric':16s} {'Baseline':>12s} {'Candidate':>12s} {'Difference':>12s}")
    for label, bv, cv in rows:
        bv_s = f"{bv:.4f}" if isinstance(bv, float) else ("n/a" if bv is None else str(bv))
        cv_s = f"{cv:.4f}" if isinstance(cv, float) else ("n/a" if cv is None else str(cv))
        diff = (cv - bv) if isinstance(bv, (int, float)) and isinstance(cv, (int, float)) else None
        diff_s = f"{diff:+.4f}" if diff is not None else "n/a"
        lines.append(f"{label:16s} {bv_s:>12s} {cv_s:>12s} {diff_s:>12s}")
    lines.append("")
    lines.append(f"baseline sample:  {b.sample_label}  (n={b.trade_count})")
    lines.append(f"candidate sample: {c.sample_label}  (n={c.trade_count})")
    lines.append(f"OOS: {b.oos}")
    if b.average_r_note != "computed from the DNA's fixed_pct stop distance":
        lines.append(f"Average R: {b.average_r_note}")
    return "\n".join(lines)


async def list_experiments(db: AsyncSession, *, kind: str | None = None, limit: int = 50) -> list[Experiment]:
    """Never overwrites, so this is simply every row, newest first — no
    "current state" collapsing the way champion/challenger lookups do."""
    stmt = select(Experiment).order_by(Experiment.created_at.desc()).limit(limit)
    if kind is not None:
        stmt = stmt.where(Experiment.kind == kind)
    return list((await db.execute(stmt)).scalars().all())


def diff_experiments(a: Experiment, b: Experiment) -> dict[str, tuple[object, object, object]]:
    """{field: (a_value, b_value, difference_or_None)} for every numeric field
    present in both experiments' `.result` (falls back to `parameters` for
    non-result context like DNA); non-numeric or missing fields report a plain
    (a, b, None) tuple so nothing is silently dropped from the diff."""
    ra, rb = (a.result or {}), (b.result or {})
    keys = sorted(set(ra) | set(rb))
    out: dict[str, tuple[object, object, object]] = {}
    for k in keys:
        va, vb = ra.get(k), rb.get(k)
        delta = (vb - va) if isinstance(va, (int, float)) and isinstance(vb, (int, float)) and not isinstance(va, bool) else None
        out[k] = (va, vb, delta)
    return out
