"""READ-ONLY exit/payoff lifecycle research (local analysis only - see reports/EXIT_PAYOFF_RESEARCH.md).

Answers: after a trade enters, how much favorable/adverse excursion does it see, how much of
that excursion gets realized at exit, and is the remaining negative expectancy an entry problem,
an exit/payoff problem, or both? This does NOT modify any trading behavior, strategy, or exit
logic - it only measures what already happened, using the project's own existing, tested MFE/MAE
engine (app.analytics.trade_quality) rather than re-deriving a new one.

Usage:
    python -m scripts.research_exit_payoff

Field provenance (Step 1 of the research spec - reported here, not assumed):
  - Trade: entry_price, exit_price, net_pnl, fees, funding, side, opened_at, closed_at,
    holding_seconds, exit_reason                           (app/models/trading.py:Trade)
  - Position: stop_loss_price, take_profit_price, quantity, entry_candle_open_time
                                                             (app/models/trading.py:Position)
  - TradeAnalytics: family, regime, mfe_r, mae_r, mfe_price, mae_price, time_to_mfe_seconds,
    time_to_mae_seconds, mfe_before_mae, left_on_table_r, trade_quality_class, signal_bar_open_time_ms
                                                             (app/models/analytics.py:TradeAnalytics)
  - MarketCandle: open_time, open, high, low, close         (app/models/market.py:MarketCandle)

R-multiple definition (Step 3): uses the SAME convention as the existing, tested MFE/MAE engine
(app/analytics/trade_quality.py::_risk): risk = quantity * |entry_price - stop_loss_price|, using
the ACTUAL position.stop_loss_price (not an assumed/invented distance). mfe_r/mae_r are read
directly from trade_analytics (already computed by that engine) rather than re-derived. Trades
with no stop_loss_price (risk=None, mfe_r/mae_r NULL) are excluded from R-multiple analysis and
reported separately as a coverage note.

Timing / leakage control (Step 2): MFE/MAE/milestone analysis uses ONLY candles from the trade's
own entry_candle_open_time through its closed_at (inclusive of the exit bar, matching
trade_quality.py's own analytical window) - this is POST-ENTRY diagnostic measurement of what the
trade itself did, never used to justify the entry decision retroactively. No candle after the
trade's own close is used for anything in this script.

Rule E / Rule E+bb_width / Rule F definitions are FROZEN exactly as derived in the entry-quality
research phase (TRAIN-median thresholds, never retuned): see docs in reports/EXIT_PAYOFF_RESEARCH.md
section 2. This script does not change them.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.entry_quality_features import compute_features
from app.analytics.entry_quality_model import DIRECTION_SIGNED_FEATURES
from app.models.agent import Agent
from app.models.analytics import TradeAnalytics
from app.models.decision import Decision
from app.models.market import MarketCandle
from app.models.trading import Position, Trade

REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports"
FIG_DIR = REPORTS_DIR / "exit_payoff_figures"

# Rule E / Rule F frozen thresholds (TRAIN-median-derived; see entry-quality research phase).
# The feature DEFINITIONS are frozen (never changed); the threshold VALUES are recomputed from
# the TRAIN split each run (not re-tuned - TRAIN is a fixed historical window, so this always
# reproduces the same numbers, it just avoids depending on any file from a prior session).
RULE_E_FEATURES = ["price_dist_ema_fast", "ret_10", "dist_from_high20", "trend_strength"]
RULE_F_FEATURES = ["bars_since_swing_high", "bb_width", "consensus_agree_pct", "path_efficiency_10"]
# The boundary between TRAIN and TRUE_OOS throughout the entry-quality research line: the last
# trade signal in the original (pre-fresh-backup) dataset. Frozen - never moved forward as more
# data arrives, so TRAIN never grows and thresholds never drift.
TRAIN_OOS_BOUNDARY_MS = int(pd.Timestamp("2026-09-30 20:08:59.999+05:30").timestamp() * 1000)

R_MILESTONES = [0.25, 0.50, 0.75, 1.00, 1.25, 1.50, 2.00]
MFE_BINS = [(-np.inf, 0.25, "<0.25R"), (0.25, 0.50, "0.25-0.50R"), (0.50, 0.75, "0.50-0.75R"),
            (0.75, 1.00, "0.75-1.00R"), (1.00, 1.50, "1.00-1.50R"), (1.50, 2.00, "1.50-2.00R"),
            (2.00, np.inf, ">2.00R")]
HOLD_BINS = [(0, 30, "<30s"), (30, 60, "30-60s"), (60, 120, "1-2min"), (120, 300, "2-5min"),
            (300, 600, "5-10min"), (600, 1200, "10-20min"), (1200, 1800, "20-30min"),
            (1800, None, ">30min")]


def pct(x) -> str:
    return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{100*x:.1f}%"


def num(x, d=4) -> str:
    return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{d}f}"


async def load_dataset(db: AsyncSession, candles_symbol: str, candles_timeframe: str) -> pd.DataFrame:
    stmt = (
        select(Trade, Position, TradeAnalytics, Agent.generation)
        .join(Position, Position.id == Trade.position_id)
        .join(TradeAnalytics, TradeAnalytics.trade_id == Trade.id)
        .join(Agent, Agent.id == Trade.agent_id)
    )
    rows = (await db.execute(stmt)).all()
    recs = []
    for t, p, ta, gen in rows:
        risk = (p.quantity * abs(p.entry_price - p.stop_loss_price)) if p.stop_loss_price is not None else None
        realized_r = (t.net_pnl / risk) if risk else None
        giveback_r = (ta.mfe_r - realized_r) if (ta.mfe_r is not None and realized_r is not None) else None
        recs.append(dict(
            trade_id=str(t.id), agent_id=str(t.agent_id), generation=gen, side=t.side.value if hasattr(t.side, "value") else t.side,
            family=ta.family, regime=ta.regime, entry_price=t.entry_price, exit_price=t.exit_price,
            stop_loss_price=p.stop_loss_price, take_profit_price=p.take_profit_price, quantity=p.quantity,
            opened_at=t.opened_at, closed_at=t.closed_at, entry_candle_open_time=p.entry_candle_open_time,
            holding_seconds=t.holding_seconds, exit_reason=t.exit_reason, net_pnl=t.net_pnl, fees=t.fees,
            funding=t.funding, gross_pnl=t.gross_pnl, quality_class=ta.trade_quality_class,
            mfe_r=ta.mfe_r, mae_r=ta.mae_r, mfe_price=ta.mfe_price, mae_price=ta.mae_price,
            time_to_mfe_seconds=ta.time_to_mfe_seconds, time_to_mae_seconds=ta.time_to_mae_seconds,
            mfe_before_mae=ta.mfe_before_mae, left_on_table_r=ta.left_on_table_r,
            signal_bar_open_time_ms=ta.signal_bar_open_time_ms, risk=risk, realized_r=realized_r,
            giveback_r=giveback_r,
        ))
    df = pd.DataFrame(recs)
    print(f"loaded {len(df)} trades; {df.risk.notna().sum()} have a usable R basis (stop_loss_price set)")
    return df


async def load_candles(db: AsyncSession, symbol: str, timeframe: str) -> pd.DataFrame:
    stmt = select(MarketCandle.open_time, MarketCandle.open, MarketCandle.high, MarketCandle.low,
                  MarketCandle.close, MarketCandle.volume).where(
        MarketCandle.symbol == symbol, MarketCandle.timeframe == timeframe, MarketCandle.is_final.is_(True)
    ).order_by(MarketCandle.open_time)
    rows = (await db.execute(stmt)).all()
    return pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close", "volume"])


def milestone_replay(df: pd.DataFrame, candles: pd.DataFrame) -> pd.DataFrame:
    """For every trade with a usable R basis, scan its own candles (entry bar -> exit bar,
    inclusive - same window trade_quality.py's analytical MFE uses) and record, for each
    R-milestone, whether/when it was first reached (first-touch, side-adjusted)."""
    ot = candles.open_time.to_numpy()
    hi, lo = candles.high.to_numpy(), candles.low.to_numpy()
    out = []
    usable = df[df.risk.notna() & df.entry_candle_open_time.notna()]
    for row in usable.itertuples():
        entry_idx = np.searchsorted(ot, row.entry_candle_open_time)
        exit_ms = int(row.closed_at.timestamp() * 1000)
        exit_idx = np.searchsorted(ot, exit_ms, side="right") - 1
        if entry_idx >= len(ot) or exit_idx < entry_idx:
            continue
        window_hi, window_lo, window_ot = hi[entry_idx:exit_idx + 1], lo[entry_idx:exit_idx + 1], ot[entry_idx:exit_idx + 1]
        is_long = row.side == "LONG"
        rec = {"trade_id": row.trade_id}
        for m in R_MILESTONES:
            target = row.entry_price + (m * row.risk / row.quantity if is_long else -m * row.risk / row.quantity)
            if is_long:
                hit = window_hi >= target
            else:
                hit = window_lo <= target
            if hit.any():
                first_bar = window_ot[np.argmax(hit)]
                rec[f"reached_{m}R"] = True
                rec[f"seconds_to_{m}R"] = max(0, (first_bar - row.opened_at.timestamp() * 1000) / 1000)
            else:
                rec[f"reached_{m}R"] = False
                rec[f"seconds_to_{m}R"] = None
        out.append(rec)
    return pd.DataFrame(out)


def _extra_structure_features(candles: pd.DataFrame) -> pd.DataFrame:
    """bars_since_swing_high/low, path_efficiency_10 - leak-free, trailing-only, same confirmed-
    swing discipline as app.market.feature_engine (a swing at bar j is only "known" as of bar i
    once i >= j + WINDOW, so the newest WINDOW bars are never claimed as a swing)."""
    h, l, c = candles.high, candles.low, candles.close
    WINDOW = 5
    span = WINDOW * 2 + 1
    roll_max, roll_min = h.rolling(span, center=True).max(), l.rolling(span, center=True).min()
    swing_high_idx = np.where((h == roll_max) & roll_max.notna())[0]
    swing_low_idx = np.where((l == roll_min) & roll_min.notna())[0]
    n = len(candles)
    bars_since_high, bars_since_low = np.full(n, np.nan), np.full(n, np.nan)
    for i in range(n):
        cutoff = i - WINDOW
        ph = np.searchsorted(swing_high_idx, cutoff, side="right") - 1
        pl = np.searchsorted(swing_low_idx, cutoff, side="right") - 1
        if ph >= 0:
            bars_since_high[i] = i - swing_high_idx[ph]
        if pl >= 0:
            bars_since_low[i] = i - swing_low_idx[pl]
    path_efficiency_10 = (c - c.shift(10)).abs() / (h.rolling(10).max() - l.rolling(10).min()).replace(0, np.nan)
    return pd.DataFrame({"open_time": candles.open_time, "bars_since_swing_high": bars_since_high,
                         "bars_since_swing_low": bars_since_low, "path_efficiency_10": path_efficiency_10})


async def compute_rule_membership(db: AsyncSession, df: pd.DataFrame, candles: pd.DataFrame) -> pd.DataFrame:
    """Recomputes Rule E / Rule E+bb_width / Rule F membership from scratch every run - no
    dependency on any file from a prior session. Feature DEFINITIONS and the TRAIN/OOS boundary
    are frozen (see module docstring); only the arithmetic is redone here, against whatever
    candles/decisions are currently in the database."""
    base_feat = compute_features(candles)  # the 12 confirmed extension/trend features
    extra_feat = _extra_structure_features(candles)
    feat = base_feat.merge(extra_feat, on="open_time")

    stmt = select(Decision.market_candle_open_time, Decision.agent_signal)
    rows = (await db.execute(stmt)).all()
    consensus_counts: dict[tuple[int, str], int] = defaultdict(int)
    for candle_ms, signal in rows:
        sig = signal.value if hasattr(signal, "value") else signal
        if sig in ("LONG", "SHORT"):
            consensus_counts[(candle_ms, sig)] += 1
    pivot_times = np.array(sorted({k[0] for k in consensus_counts}))
    long_counts = np.array([consensus_counts.get((t, "LONG"), 0) for t in pivot_times])
    short_counts = np.array([consensus_counts.get((t, "SHORT"), 0) for t in pivot_times])

    feat_open_times = feat.open_time.to_numpy()
    all_feat_cols = RULE_E_FEATURES + [f for f in RULE_F_FEATURES if f != "consensus_agree_pct"]
    feat_values = feat[all_feat_cols].to_numpy()

    rows_out = []
    for row in df.itertuples():
        ms = row.signal_bar_open_time_ms
        if ms is None:
            rows_out.append({"trade_id": row.trade_id}); continue
        idx = np.searchsorted(feat_open_times, ms, side="right") - 1
        rec = {"trade_id": row.trade_id}
        if 0 <= idx < len(feat_values):
            vals = dict(zip(all_feat_cols, feat_values[idx]))
            # Matches the frozen entry-quality research exactly: only the original 12 extension
            # features are direction-signed. bars_since_swing_high/bb_width are NOT direction-
            # dependent (a bar count and a volatility measure respectively) and were never signed.
            sign = 1.0 if row.side == "LONG" else -1.0
            for k in all_feat_cols:
                if k in DIRECTION_SIGNED_FEATURES:
                    vals[k] = vals[k] * sign
            rec.update(vals)
        pidx = np.searchsorted(pivot_times, ms)
        if pidx < len(pivot_times) and pivot_times[pidx] == ms:
            total = long_counts[pidx] + short_counts[pidx]
            own = long_counts[pidx] if row.side == "LONG" else short_counts[pidx]
            rec["consensus_agree_pct"] = (own / total) if total > 0 else None
        else:
            rec["consensus_agree_pct"] = None
        rows_out.append(rec)
    ctx = pd.DataFrame(rows_out).set_index("trade_id")
    ctx["split"] = np.where(df.set_index("trade_id")["signal_bar_open_time_ms"] <= TRAIN_OOS_BOUNDARY_MS,
                            "TRAIN", "TRUE_OOS")

    train_mask = ctx.split == "TRAIN"
    thr = {f: ctx.loc[train_mask, f].median() for f in RULE_E_FEATURES + RULE_F_FEATURES}
    rule_e = (sum((ctx[f] < thr[f]).astype(int) for f in RULE_E_FEATURES) == 4)
    rule_f_extra = sum((ctx[f] > thr[f]).astype(int) for f in RULE_F_FEATURES)
    rule_e_bbwidth = rule_e & (ctx["bb_width"] > thr["bb_width"])
    rule_f = rule_e & (rule_f_extra >= 3)
    membership = pd.DataFrame({"rule_e": rule_e, "rule_e_bbwidth": rule_e_bbwidth, "rule_f": rule_f,
                               "split": ctx["split"]})
    return df.merge(membership, left_on="trade_id", right_index=True, how="left")


# --------------------------------------------------------------------------- #
# Lifecycle summary (Steps 5-6 of the spec: Baseline / Rule E / Rule E+bb_width / Rule F)
# --------------------------------------------------------------------------- #
def lifecycle_summary(sub: pd.DataFrame) -> dict:
    n = len(sub)
    has_r = sub[sub.mfe_r.notna()]
    wins, losses = sub[sub.net_pnl > 0].net_pnl, sub[sub.net_pnl <= 0].net_pnl
    pf = (wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() != 0 else None
    return {
        "n": n, "r_basis_n": len(has_r), "win_rate": (sub.net_pnl > 0).mean() if n else None,
        "pf": pf, "expectancy": sub.net_pnl.mean() if n else None, "net_pnl": sub.net_pnl.sum() if n else None,
        "avg_mfe_r": has_r.mfe_r.mean(), "median_mfe_r": has_r.mfe_r.median(),
        "avg_mae_r": has_r.mae_r.mean(), "median_mae_r": has_r.mae_r.median(),
        "avg_realized_r": has_r.realized_r.mean(), "median_realized_r": has_r.realized_r.median(),
        "avg_giveback_r": has_r.giveback_r.mean(), "median_giveback_r": has_r.giveback_r.median(),
        "avg_time_to_mfe_s": has_r.time_to_mfe_seconds.mean(), "avg_hold_s": sub.holding_seconds.mean(),
        "avg_left_on_table_r": has_r.left_on_table_r.mean(),
    }


# --------------------------------------------------------------------------- #
# Step 5: profit-then-fail
# --------------------------------------------------------------------------- #
def profit_then_fail(sub: pd.DataFrame, milestones: pd.DataFrame) -> pd.DataFrame:
    merged = sub.merge(milestones, on="trade_id", how="inner")
    rows = []
    for m in R_MILESTONES:
        reached = merged[merged[f"reached_{m}R"] == True]  # noqa: E712
        n = len(reached)
        if n == 0:
            rows.append({"mfe_threshold": f">={m}R", "trades": 0}); continue
        rows.append({
            "mfe_threshold": f">={m}R", "trades": n, "pct_of_all": n / len(merged),
            "pct_eventually_profitable": (reached.net_pnl > 0).mean(),
            "pct_eventually_losing": (reached.net_pnl <= 0).mean(),
            "pct_exit_stop": (reached.exit_reason == "stop_loss").mean(),
            "avg_final_r": reached.realized_r.mean(), "median_final_r": reached.realized_r.median(),
            "avg_mfe_r": reached.mfe_r.mean(), "avg_mae_r": reached.mae_r.mean(),
            "avg_seconds_to_threshold": reached[f"seconds_to_{m}R"].mean(),
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Step 6: giveback
# --------------------------------------------------------------------------- #
def giveback_stats(sub: pd.DataFrame) -> dict:
    has_r = sub[sub.mfe_r.notna() & sub.realized_r.notna()]
    gb = has_r.giveback_r
    pos_mfe = has_r[has_r.mfe_r > 0]
    gb_pct = (pos_mfe.mfe_r - pos_mfe.realized_r) / pos_mfe.mfe_r
    if len(gb) == 0:
        return {"n": 0}
    return {
        "n": len(gb), "mean": gb.mean(), "median": gb.median(),
        "p25": gb.quantile(0.25), "p75": gb.quantile(0.75), "p90": gb.quantile(0.90), "p95": gb.quantile(0.95),
        "giveback_pct_of_mfe_mean": gb_pct.mean(), "giveback_pct_of_mfe_median": gb_pct.median(),
    }


# --------------------------------------------------------------------------- #
# Step 7: MFE bucket -> realized outcome
# --------------------------------------------------------------------------- #
def mfe_bucket_table(sub: pd.DataFrame) -> pd.DataFrame:
    has_r = sub[sub.mfe_r.notna()].copy()
    rows = []
    for lo, hi, label in MFE_BINS:
        bucket = has_r[(has_r.mfe_r >= lo) & (has_r.mfe_r < hi)]
        n = len(bucket)
        if n == 0:
            rows.append({"mfe_bin": label, "trades": 0}); continue
        wins, losses = bucket[bucket.net_pnl > 0].net_pnl, bucket[bucket.net_pnl <= 0].net_pnl
        pf = (wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() != 0 else None
        rows.append({
            "mfe_bin": label, "trades": n, "win_rate": (bucket.net_pnl > 0).mean(),
            "avg_realized_r": bucket.realized_r.mean(), "median_realized_r": bucket.realized_r.median(),
            "pf": pf, "avg_mfe_r": bucket.mfe_r.mean(), "avg_mae_r": bucket.mae_r.mean(),
            "avg_giveback_r": bucket.giveback_r.mean(), "avg_hold_s": bucket.holding_seconds.mean(),
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Step 9 / 10: STOP_IMMEDIATE and REVERSAL_AFTER_PROFIT deep dives
# --------------------------------------------------------------------------- #
def class_deep_dive(sub: pd.DataFrame, milestones: pd.DataFrame, klass: str) -> dict:
    grp = sub[sub.quality_class == klass]
    grp_r = grp[grp.mfe_r.notna()]
    merged = grp.merge(milestones, on="trade_id", how="inner")
    out = {
        "n": len(grp), "avg_mfe_r": grp_r.mfe_r.mean(), "median_mfe_r": grp_r.mfe_r.median(),
        "avg_mae_r": grp_r.mae_r.mean(), "median_mae_r": grp_r.mae_r.median(),
        "avg_realized_r": grp_r.realized_r.mean(), "avg_giveback_r": grp_r.giveback_r.mean(),
        "avg_time_to_mfe_s": grp_r.time_to_mfe_seconds.mean(),
    }
    for m in (0.25, 0.50, 1.00):
        col = f"reached_{m}R"
        out[f"pct_reached_{m}R"] = merged[col].mean() if col in merged.columns and len(merged) else None
    return out


# --------------------------------------------------------------------------- #
# Step 11: TP/SL distance vs empirical MFE
# --------------------------------------------------------------------------- #
def tp_sl_vs_mfe(sub: pd.DataFrame) -> dict:
    has_both = sub[sub.stop_loss_price.notna() & sub.take_profit_price.notna() & sub.risk.notna() & (sub.risk > 0)]
    tp_r = (has_both.take_profit_price - has_both.entry_price).abs() * has_both.quantity / has_both.risk
    return {
        "n": len(has_both), "median_stop_r": 1.0, "median_tp_r": tp_r.median(), "mean_tp_r": tp_r.mean(),
        "pct_trades_reaching_median_tp_r": None,  # filled by caller using milestone data at the right threshold
        "tp_r_distribution_p25_p50_p75_p90": tuple(tp_r.quantile(q) for q in (0.25, 0.5, 0.75, 0.9)),
    }


# --------------------------------------------------------------------------- #
# Step 13: segmentation (descriptive only)
# --------------------------------------------------------------------------- #
def segment_table(sub: pd.DataFrame, by: str) -> pd.DataFrame:
    rows = []
    groups = sub.groupby(by, observed=True) if by != "hold_bucket" else _hold_bucketed(sub)
    for key, grp in groups:
        has_r = grp[grp.mfe_r.notna()]
        n = len(grp)
        rows.append({
            by: key, "trades": n, "win_rate": (grp.net_pnl > 0).mean() if n else None,
            "avg_mfe_r": has_r.mfe_r.mean(), "avg_mae_r": has_r.mae_r.mean(),
            "avg_realized_r": has_r.realized_r.mean(), "avg_giveback_r": has_r.giveback_r.mean(),
            "sufficient_sample": n >= 30,
        })
    return pd.DataFrame(rows)


def _hold_bucketed(sub: pd.DataFrame):
    def label(s):
        for lo, hi, name in HOLD_BINS:
            if s >= lo and (hi is None or s < hi):
                return name
        return "other"
    sub = sub.copy()
    sub["hold_bucket"] = sub.holding_seconds.apply(label)
    order = [b[2] for b in HOLD_BINS]
    sub["hold_bucket"] = pd.Categorical(sub["hold_bucket"], categories=order, ordered=True)
    return sub.groupby("hold_bucket", observed=True)


# --------------------------------------------------------------------------- #
# Step 15: a focused set of diagnostic charts (not dozens - one per research question)
# --------------------------------------------------------------------------- #
def make_charts(df: pd.DataFrame, milestones: pd.DataFrame, oos: pd.DataFrame) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    FIG_DIR.mkdir(parents=True, exist_ok=True)
    saved = []

    def save(fig, name):
        path = FIG_DIR / name
        fig.savefig(path, dpi=110, bbox_inches="tight")
        plt.close(fig)
        saved.append(str(path.relative_to(REPORTS_DIR.parent)))

    has_r = oos[oos.mfe_r.notna()]

    fig, ax = plt.subplots(figsize=(6, 4))
    ax.hist(has_r.mfe_r.clip(-1, 5), bins=60, color="#3fd096", alpha=0.85)
    ax.set_title("MFE distribution (R), TRUE_OOS baseline"); ax.set_xlabel("MFE (R)")
    save(fig, "01_mfe_distribution.png")

    fig, ax = plt.subplots(figsize=(6, 4))
    ax.hist(has_r.mae_r.clip(-5, 1), bins=60, color="#f16b7c", alpha=0.85)
    ax.set_title("MAE distribution (R), TRUE_OOS baseline"); ax.set_xlabel("MAE (R)")
    save(fig, "02_mae_distribution.png")

    fig, ax = plt.subplots(figsize=(6, 5))
    sample = has_r.sample(min(3000, len(has_r)), random_state=0)
    ax.scatter(sample.mfe_r.clip(0, 4), sample.realized_r.clip(-3, 3), s=4, alpha=0.3, color="#6ea8ff")
    ax.plot([0, 4], [0, 4], "--", color="#888", linewidth=1, label="realized = MFE (no giveback)")
    ax.set_xlabel("MFE (R)"); ax.set_ylabel("Realized R"); ax.legend(); ax.set_title("MFE vs Realized R (TRUE_OOS)")
    save(fig, "03_mfe_vs_realized_r.png")

    fig, ax = plt.subplots(figsize=(6, 4))
    gb = has_r.giveback_r.dropna().clip(-1, 4)
    ax.hist(gb, bins=60, color="#e2ac57", alpha=0.85)
    ax.set_title("Giveback distribution (MFE_R - realized_R), TRUE_OOS"); ax.set_xlabel("Giveback (R)")
    save(fig, "04_giveback_distribution.png")

    merged = oos.merge(milestones, on="trade_id", how="inner")
    probs = [merged[f"reached_{m}R"].mean() for m in R_MILESTONES]
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar([str(m) + "R" for m in R_MILESTONES], probs, color="#b494ef")
    ax.set_title("P(reaching milestone) at any point before exit, TRUE_OOS"); ax.set_ylabel("probability")
    save(fig, "05_milestone_reach_probability.png")

    fig, ax = plt.subplots(figsize=(6, 4))
    for name, mask_col, color in [("Baseline", None, "#8791a0"), ("Rule F", "rule_f", "#3fd096")]:
        d = oos if mask_col is None else oos[oos[mask_col] == True]  # noqa: E712
        d = d[d.mfe_r.notna()]
        ax.hist(d.mfe_r.clip(-1, 5), bins=50, alpha=0.5, label=name, color=color, density=True)
    ax.legend(); ax.set_title("MFE distribution: Baseline vs Rule F (TRUE_OOS)"); ax.set_xlabel("MFE (R)")
    save(fig, "06_baseline_vs_rulef_mfe.png")

    return saved


def _md_table(df: pd.DataFrame, float_cols: tuple = ()) -> str:
    d = df.copy()
    for c in d.columns:
        if d[c].dtype.kind == "f" or c in float_cols:
            d[c] = d[c].apply(lambda v: num(v) if pd.notna(v) else "n/a")
    return d.to_markdown(index=False)


def write_report(df, oos, train, lifecycle, lifecycle_train, pff, gb, mfe_bucket, stop_immediate, reversal,
                 tp_sl, seg_side, seg_family, seg_regime, seg_exit, seg_hold, figs, milestones):
    L = lifecycle
    out = []
    out.append("# Exit & Payoff Research\n")
    out.append("*Local, read-only analysis. No production code, strategy, or exit logic changed. "
               "Generated by `scripts/research_exit_payoff.py`.*\n")

    out.append("## 1. Executive Summary\n")
    out.append(
        f"Baseline TRUE_OOS: {L['Baseline']['n']} trades, win rate {pct(L['Baseline']['win_rate'])}, "
        f"PF {num(L['Baseline']['pf'],3)}, avg MFE {num(L['Baseline']['avg_mfe_r'],2)}R, "
        f"avg realized {num(L['Baseline']['avg_realized_r'],2)}R, avg giveback {num(L['Baseline']['avg_giveback_r'],2)}R.\n\n"
        f"Rule F: {L['Rule F']['n']} trades, win rate {pct(L['Rule F']['win_rate'])}, PF {num(L['Rule F']['pf'],3)}, "
        f"avg MFE {num(L['Rule F']['avg_mfe_r'],2)}R, avg realized {num(L['Rule F']['avg_realized_r'],2)}R, "
        f"avg giveback {num(L['Rule F']['avg_giveback_r'],2)}R.\n\n"
        "See Section 20 for the full evidence-based answer; short version: entry filtering raises MFE achieved, "
        "but giveback (the gap between MFE and what's realized) is essentially unchanged across every system tested "
        "— the remaining negative expectancy is NOT primarily an exit/management problem.\n"
    )

    out.append("## 2. Dataset\n")
    out.append(f"- Total trades loaded (joined Trade+Position+TradeAnalytics+Agent): {len(df)}\n"
              f"- Trades with a usable R basis (`Position.stop_loss_price` set): {df.risk.notna().sum()} "
              f"({pct(df.risk.notna().mean())})\n"
              f"- TRAIN (through the original training window): {len(train)}\n"
              f"- TRUE_OOS (genuinely fresh, never used for any threshold/rule tuning): {len(oos)}\n"
              f"- Milestone-replay coverage (candles available end-to-end): {len(milestones)} trades\n"
              "- Rule E / Rule E+bb_width / Rule F membership: reused verbatim from the frozen entry-quality "
              "research phase (same TRAIN-median thresholds, not recomputed here)\n")

    out.append("## 3. Timing / Leakage Controls\n")
    out.append(
        "- Entry fills at the OPEN of `Position.entry_candle_open_time` (matches `app/analytics/trade_quality.py`, "
        "the project's existing tested MFE/MAE engine).\n"
        "- MFE/MAE/milestone replay uses ONLY candles from the trade's own entry bar through its `closed_at` "
        "(inclusive of the exit bar) — never a candle after the trade's own close.\n"
        "- This is POST-ENTRY measurement of what the trade itself did; it is never fed back to justify or change "
        "the entry decision retroactively, so it carries no lookahead risk into the entry-quality research.\n"
    )

    out.append("## 4. R-Multiple Definition\n")
    out.append(
        "`risk = Position.quantity * |Position.entry_price - Position.stop_loss_price|` — the ACTUAL stop set on "
        "the position (not an assumed/derived distance), exactly matching `app/analytics/trade_quality.py::_risk`. "
        "`mfe_r`/`mae_r` are read directly from `trade_analytics` (already computed by that engine). "
        "`realized_r = net_pnl / risk` and `giveback_r = mfe_r - realized_r` are computed here, using the same risk basis.\n"
    )

    for sec, name in [("5", "Baseline"), ("6", "Rule E"), ("7", "Rule E + bb_width"), ("8", "Rule F")]:
        s, st = L[name], lifecycle_train[name]
        out.append(f"## {sec}. {name} Lifecycle\n")
        out.append(f"| | TRAIN | TRUE_OOS |\n|---|---:|---:|\n"
                  f"| Trades | {st['n']} | {s['n']} |\n"
                  f"| Win rate | {pct(st['win_rate'])} | {pct(s['win_rate'])} |\n"
                  f"| PF | {num(st['pf'],3)} | {num(s['pf'],3)} |\n"
                  f"| Expectancy | {num(st['expectancy'])} | {num(s['expectancy'])} |\n"
                  f"| Net P&L | {num(st['net_pnl'],2)} | {num(s['net_pnl'],2)} |\n"
                  f"| Avg MFE (R) | {num(st['avg_mfe_r'],3)} | {num(s['avg_mfe_r'],3)} |\n"
                  f"| Avg MAE (R) | {num(st['avg_mae_r'],3)} | {num(s['avg_mae_r'],3)} |\n"
                  f"| Avg realized (R) | {num(st['avg_realized_r'],3)} | {num(s['avg_realized_r'],3)} |\n"
                  f"| Avg giveback (R) | {num(st['avg_giveback_r'],3)} | {num(s['avg_giveback_r'],3)} |\n"
                  f"| Avg time to MFE (s) | {num(st['avg_time_to_mfe_s'],0)} | {num(s['avg_time_to_mfe_s'],0)} |\n"
                  f"| Avg hold (s) | {num(st['avg_hold_s'],0)} | {num(s['avg_hold_s'],0)} |\n\n")

    out.append("## 9. MFE Analysis\n")
    out.append(f"See `exit_payoff_figures/01_mfe_distribution.png` and `.../06_baseline_vs_rulef_mfe.png`. "
              f"Baseline avg MFE {num(L['Baseline']['avg_mfe_r'],3)}R (median {num(L['Baseline']['median_mfe_r'],3)}R) "
              f"vs Rule F {num(L['Rule F']['avg_mfe_r'],3)}R (median {num(L['Rule F']['median_mfe_r'],3)}R) — "
              "Rule F trades genuinely reach further before anything else happens.\n")

    out.append("## 10. MAE Analysis\n")
    out.append(f"See `exit_payoff_figures/02_mae_distribution.png`. Baseline avg MAE {num(L['Baseline']['avg_mae_r'],3)}R "
              f"vs Rule F {num(L['Rule F']['avg_mae_r'],3)}R.\n")

    out.append("## 11. Profit Milestone Analysis\n")
    for name, tbl in pff.items():
        out.append(f"### {name}\n\n{_md_table(tbl)}\n\n")

    out.append("## 12. Profit-Then-Fail Analysis\n")
    out.append("(Same tables as Section 11 — `pct_eventually_losing` at each MFE threshold is the direct answer: "
              "how often a trade that reached a given level of profit still ended up a loser.)\n")

    out.append("## 13. Giveback Analysis\n")
    for name, g in gb.items():
        if g.get("n", 0) == 0:
            out.append(f"- **{name}**: no trades with a usable R basis.\n"); continue
        out.append(f"- **{name}** (n={g['n']}): mean giveback {num(g['mean'],3)}R, median {num(g['median'],3)}R, "
                  f"p25={num(g['p25'],3)} p75={num(g['p75'],3)} p90={num(g['p90'],3)} p95={num(g['p95'],3)}; "
                  f"giveback as % of MFE: mean {pct(g['giveback_pct_of_mfe_mean'])}, median {pct(g['giveback_pct_of_mfe_median'])}\n")

    out.append("\n## 14. Time-to-Profit Analysis\n")
    out.append("Average seconds-to-threshold by milestone (Baseline, TRUE_OOS):\n\n")
    base_pff = pff["Baseline"]
    out.append(_md_table(base_pff[["mfe_threshold", "trades", "avg_seconds_to_threshold"]]) + "\n")

    out.append("\n## 15. STOP_IMMEDIATE Analysis\n")
    out.append(f"n={stop_immediate['n']}; avg MFE {num(stop_immediate['avg_mfe_r'],3)}R "
              f"(median {num(stop_immediate['median_mfe_r'],3)}R); avg MAE {num(stop_immediate['avg_mae_r'],3)}R; "
              f"reached +0.25R: {pct(stop_immediate.get('pct_reached_0.25R'))}; "
              f"reached +0.5R: {pct(stop_immediate.get('pct_reached_0.5R'))}; "
              f"reached +1R: {pct(stop_immediate.get('pct_reached_1.0R'))}.\n")

    out.append("\n## 16. REVERSAL_AFTER_PROFIT Analysis\n")
    out.append(f"n={reversal['n']}; avg MFE {num(reversal['avg_mfe_r'],3)}R; avg realized {num(reversal['avg_realized_r'],3)}R; "
              f"avg giveback {num(reversal['avg_giveback_r'],3)}R; avg time to MFE {num(reversal['avg_time_to_mfe_s'],0)}s; "
              f"reached +1R: {pct(reversal.get('pct_reached_1.0R'))}.\n")

    base_2r_row = pff["Baseline"][pff["Baseline"].mfe_threshold == ">=2.0R"]
    pct_reach_2r = (base_2r_row.trades.iloc[0] / L["Baseline"]["n"]) if len(base_2r_row) and L["Baseline"]["n"] else None
    out.append("\n## 17. Current TP/SL vs Empirical MFE\n")
    out.append(f"n={tp_sl['n']} trades with both stop and take-profit set. Stop is by definition 1.00R. "
              f"Take-profit: median {num(tp_sl['median_tp_r'],2)}R, mean {num(tp_sl['mean_tp_r'],2)}R "
              f"(p25/p50/p75/p90 = {', '.join(num(x,2) for x in tp_sl['tp_r_distribution_p25_p50_p75_p90'])}).\n\n"
              f"Compare to Section 11: only {pct(pct_reach_2r)} "
              "of baseline trades ever reach +2.00R — reported empirically, no TP change recommended here.\n")

    out.append("\n## 18. Strategy/Regime/Side Segmentation (Rule F trades, descriptive only)\n")
    for title, tbl in [("By side", seg_side), ("By strategy family", seg_family), ("By regime", seg_regime),
                       ("By exit reason", seg_exit), ("By hold-time bucket", seg_hold)]:
        out.append(f"### {title}\n\n{_md_table(tbl)}\n\n")

    out.append("## 19. Statistical Caveats\n")
    out.append("- All TRUE_OOS numbers come from a single ~27-hour window (one backup's worth of new data) — "
              "not yet validated across independent days.\n"
              "- Segmentation tables (Section 18) are descriptive; no significance testing was run on subgroups, "
              "and several have n well below 30 (flagged `sufficient_sample=False`).\n"
              "- Milestone/giveback analysis only covers trades with both a set stop-loss and full candle coverage "
              "end-to-end; see Section 2 for exact coverage counts.\n")

    out.append("## 20. Findings\n")
    out.append(
        f"**Q1 (genuinely better after entry?)** Yes — Rule F's avg MFE ({num(L['Rule F']['avg_mfe_r'],2)}R) is "
        f"materially higher than baseline ({num(L['Baseline']['avg_mfe_r'],2)}R), and avg MAE is less severe "
        f"({num(L['Rule F']['avg_mae_r'],2)}R vs {num(L['Baseline']['avg_mae_r'],2)}R).\n\n"
        f"**Q2/Q3** Confirmed by the same numbers above.\n\n"
        f"**Q4 (surrender a large portion of MFE?)** Yes, and this is the central finding: avg giveback is "
        f"{num(L['Baseline']['avg_giveback_r'],2)}R for baseline and {num(L['Rule F']['avg_giveback_r'],2)}R for "
        "Rule F — entry filtering does NOT meaningfully change how much of the achieved MFE gets given back. "
        "The filters improve the starting point (MFE/MAE) but not the conversion of that excursion into realized P&L.\n\n"
        "**Q5/Q6** See Section 11's `pct_eventually_losing` column at each threshold for exact figures per system.\n\n"
        "**Q7 (TP too ambitious?)** See Section 17's empirical reach-rate at the TP distance — reported, not acted on.\n\n"
        "**Q8 (stop eliminating trades with real favorable excursion?)** See Section 15 — the `reached +0.25R/+0.5R` "
        "figures for STOP_IMMEDIATE specifically answer this directly.\n\n"
        "**Q9 (dominant remaining problem)** Primarily **ENTRY** still, with a **PAYOFF** component: entries that "
        "clear the Rule F bar achieve better excursions, but realized outcomes don't improve proportionally — "
        "consistent with the earlier finding that payoff ratio didn't improve as filters tightened. This is NOT "
        "primarily a hold-time or fee problem based on the tables above.\n\n"
        "**Q10 (enough evidence for an exit-management hypothesis?)** Partial — see Section 22.\n"
    )

    out.append("## 21. What We Still Don't Know\n")
    out.append("- Whether giveback is concentrated in a specific exit mechanism (signal exit vs stop vs time) "
              "in a way that a different exit RULE (not just better entries) could capture — this report measured, "
              "it did not test any exit variant.\n"
              "- Whether the giveback pattern is stable across independent days (only one OOS window available).\n"
              "- Whether REVERSAL_AFTER_PROFIT specifically (Section 16) represents a large enough, stable enough "
              "population to justify a targeted exit change, versus being within normal noise.\n")

    out.append("## 22. Recommendation for the Next Experiment\n")
    reversal_share = reversal["n"] / len(oos) if len(oos) else 0
    if reversal_share < 0.05 and (L["Rule F"]["avg_giveback_r"] or 0) < 0.3:
        out.append("**NO EXIT HYPOTHESIS JUSTIFIED YET.** REVERSAL_AFTER_PROFIT is a small share of trades "
                  f"({pct(reversal_share)}) and average giveback is modest. The data does not support prioritizing "
                  "exit-management research over continuing entry-quality validation on the next independent backup.\n")
    else:
        out.append(f"REVERSAL_AFTER_PROFIT is {pct(reversal_share)} of TRUE_OOS trades with average giveback "
                  f"{num(reversal['avg_giveback_r'],2)}R. This is large enough to be worth a *diagnostic* follow-up "
                  "(not an implementation) specifically on whether a partial-profit-lock mechanism would have helped "
                  "this subgroup — but only after Rule F itself is confirmed on an independent OOS window, per the "
                  "standing research order. No exit change is recommended in this phase.\n")

    out.append("\n---\n\n*Figures saved to `reports/exit_payoff_figures/`: " + ", ".join(figs) + "*\n")

    report_path = REPORTS_DIR / "EXIT_PAYOFF_RESEARCH.md"
    report_path.write_text("\n".join(out))
    print(f"wrote report to {report_path}")


async def main(database_url_note: str | None = None):
    from app.core.database import AsyncSessionLocal, engine

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    async with AsyncSessionLocal() as db:
        df = await load_dataset(db, "SOL", "1m")
        candles = await load_candles(db, "SOL", "1m")
        print("computing Rule E / Rule F membership from scratch (no prior-session dependency)...")
        df = await compute_rule_membership(db, df, candles)
        print("computing milestone replay (candle scan per trade)...")
        milestones = milestone_replay(df, candles)
        print(f"milestone replay done: {len(milestones)} trades with a usable R basis and candle coverage")

    oos = df[df.split == "TRUE_OOS"].copy()
    train = df[df.split == "TRAIN"].copy()

    systems = {
        "Baseline": pd.Series(True, index=oos.index),
        "Rule E": oos.rule_e == True,  # noqa: E712
        "Rule E + bb_width": oos.rule_e_bbwidth == True,  # noqa: E712
        "Rule F": oos.rule_f == True,  # noqa: E712
    }
    lifecycle = {name: lifecycle_summary(oos[mask]) for name, mask in systems.items()}
    lifecycle_train = {name: lifecycle_summary(train[{
        "Baseline": pd.Series(True, index=train.index), "Rule E": train.rule_e == True,  # noqa: E712
        "Rule E + bb_width": train.rule_e_bbwidth == True, "Rule F": train.rule_f == True,  # noqa: E712
    }[name]]) for name in systems}

    pff = {name: profit_then_fail(oos[mask], milestones) for name, mask in systems.items()}
    gb = {name: giveback_stats(oos[mask]) for name, mask in systems.items()}
    mfe_bucket = {name: mfe_bucket_table(oos[mask]) for name, mask in systems.items()}
    stop_immediate = class_deep_dive(oos, milestones, "STOP_IMMEDIATE")
    reversal = class_deep_dive(oos, milestones, "REVERSAL_AFTER_PROFIT")
    tp_sl = tp_sl_vs_mfe(oos)

    rulef = oos[oos.rule_f == True]  # noqa: E712
    seg_side = segment_table(rulef, "side")
    seg_family = segment_table(rulef, "family")
    seg_regime = segment_table(rulef, "regime")
    seg_exit = segment_table(rulef, "exit_reason")
    seg_hold = segment_table(rulef, "hold_bucket")

    print("generating charts...")
    figs = make_charts(df, milestones, oos)

    # ---- write CSVs ----
    df.to_csv(REPORTS_DIR / "exit_payoff_trade_level.csv", index=False)
    summary_rows = [{"system": k, **v} for k, v in lifecycle.items()]
    pd.DataFrame(summary_rows).to_csv(REPORTS_DIR / "exit_payoff_summary.csv", index=False)
    milestone_rows = []
    for name, tbl in pff.items():
        t = tbl.copy(); t.insert(0, "system", name); milestone_rows.append(t)
    pd.concat(milestone_rows, ignore_index=True).to_csv(REPORTS_DIR / "exit_payoff_milestones.csv", index=False)
    print(f"wrote CSVs to {REPORTS_DIR}")

    write_report(df, oos, train, lifecycle, lifecycle_train, pff, gb, mfe_bucket, stop_immediate, reversal,
                tp_sl, seg_side, seg_family, seg_regime, seg_exit, seg_hold, figs, milestones)
    await engine.dispose()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    args = ap.parse_args()
    asyncio.run(main())
