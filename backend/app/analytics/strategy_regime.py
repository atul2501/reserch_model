"""Pure strategy x regime matrix engine: cell metrics, Wilson intervals, regime
episodes, episode block bootstrap, evidence states.

Statistical safety rules (the whole point of this module):
  * trades inside ONE regime episode share market conditions and are NOT
    independent evidence -> the bootstrap resamples EPISODES, and a cell needs
    >= MIN_EPISODES independent episodes to be TESTED;
  * win rates carry a Wilson score 95% interval (never a naive Wald interval);
  * an edge (gross or net) is only declared when the confidence interval excludes
    zero AND the cell is not under-sampled. Small-sample cells are reported with
    their numbers and an explicit UNTESTED/PROVISIONAL state — never a verdict.

The reliability math reuses the empirical-Bayes definitions of
app.analytics.shadow_fitness (UNTESTED/PROVISIONAL/TESTED) applied per cell over
net bps, so agent-evidence and cell-evidence speak the same language.
"""
from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from app.analytics.shadow_fitness import BPS_UNIT, ShadowConfig, estimate_prior, unit_result

MIN_EPISODES = 3          # independent regime episodes required for TESTED
MIN_CELL_TRADES = 10      # prior contribution threshold (matches shadow_fitness.prior_min_trades)
BOOTSTRAP_RESAMPLES = 1000
WILSON_Z = 1.959963985    # two-sided 95%

UNTESTED = "UNTESTED"
PROVISIONAL = "PROVISIONAL"
TESTED = "TESTED"


def wilson_ci(k: int, n: int, z: float = WILSON_Z) -> tuple[float, float] | None:
    """Wilson score interval for a binomial proportion. None when there is no sample."""
    if n <= 0:
        return None
    p = k / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def episode_ids(regime_rows: Iterable[tuple[int, str]]) -> dict[int, int]:
    """Map candle_open_time -> episode id.

    `regime_rows` is the ordered (candle_open_time, regime) series for one
    (symbol, timeframe). A maximal run of the same regime is one episode; ids
    are 1-based run indices over the series, so they are stable as long as
    history is append-only (new runs get new ids, old ids never change).
    """
    out: dict[int, int] = {}
    current: str | None = None
    episode = 0
    for open_time, regime in regime_rows:
        if regime != current:
            episode += 1
            current = regime
        out[open_time] = episode
    return out


def _seed(*parts: object) -> int:
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFFFFFF


def episode_block_bootstrap_ci(
    values_by_episode: dict[int, list[float]], *, seed_key: tuple[object, ...],
    resamples: int = BOOTSTRAP_RESAMPLES,
) -> tuple[float, float] | None:
    """95% CI for the pooled mean by resampling independent regime episodes.

    Deterministic: the seed is derived from the cell identity, so refreshing the
    matrix twice yields byte-identical intervals. None with < 2 episodes (an
    honest "cannot say" rather than a fake interval).
    """
    episodes = [v for v in values_by_episode.values() if v]
    if len(episodes) < 2:
        return None
    rng = np.random.default_rng(_seed(*seed_key))
    means = np.empty(resamples)
    n = len(episodes)
    for i in range(resamples):
        idx = rng.integers(0, n, size=n)
        pooled = np.concatenate([episodes[j] for j in idx])
        means[i] = pooled.mean()
    return float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


@dataclass(frozen=True)
class TradeRow:
    """The per-trade inputs of one matrix cell (fields the store slices from TradeAnalytics)."""
    net_pnl: float
    gross_pnl: float
    fees: float
    funding: float
    slippage: float
    holding_seconds: int
    mfe_r: float | None
    mae_r: float | None
    quality_class: str
    episode_id: int | None
    closed_at: float          # epoch seconds — only used for the drawdown curve ordering


def cell_metrics(rows: Sequence[TradeRow]) -> dict:
    """All cell aggregates except the evidence state (which needs the population)."""
    n = len(rows)
    wins = [r for r in rows if r.net_pnl > 0]
    losses = [r for r in rows if r.net_pnl < 0]
    net = [r.net_pnl for r in rows]
    ci = wilson_ci(len(wins), n)
    mfe = [r.mfe_r for r in rows if r.mfe_r is not None]
    mae = [r.mae_r for r in rows if r.mae_r is not None]
    gross_win = sum(r.net_pnl for r in wins)            # gross of costs within the cell's trades
    gross_loss = abs(sum(r.net_pnl for r in losses))
    return {
        "trade_count": n,
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": (len(wins) / n) if n else None,
        "win_rate_ci_low": ci[0] if ci else None,
        "win_rate_ci_high": ci[1] if ci else None,
        "gross_pnl": sum(r.gross_pnl for r in rows),
        "fees": sum(r.fees for r in rows),
        "funding": sum(r.funding for r in rows),
        "slippage": sum(r.slippage for r in rows),
        "net_pnl": sum(net),
        "avg_trade_pnl": (sum(net) / n) if n else None,
        "expectancy": (sum(net) / n) if n else None,
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else None,
        "avg_winner": (gross_win / len(wins)) if wins else None,
        "avg_loser": (-(gross_loss) / len(losses)) if losses else None,
        "avg_holding_seconds": (sum(r.holding_seconds for r in rows) / n) if n else None,
        "max_drawdown_currency": _drawdown(net, [r.closed_at for r in rows]),
        "mfe_r_mean": float(np.mean(mfe)) if mfe else None,
        "mfe_r_median": float(np.median(mfe)) if mfe else None,
        "mfe_r_p90": float(np.quantile(mfe, 0.9)) if mfe else None,
        "mae_r_mean": float(np.mean(mae)) if mae else None,
        "mae_r_median": float(np.median(mae)) if mae else None,
        "mae_r_p90": float(np.quantile(mae, 0.9)) if mae else None,
        "tp_first_pct": _class_share(rows, n, "TAKE_PROFIT_HIT"),
        "sl_first_pct": _class_share(rows, n, "STOP_IMMEDIATE"),
        "reversal_pct": _class_share(rows, n, "REVERSAL_AFTER_PROFIT"),
        "cost_eaten_pct": _class_share(rows, n, "COST_EATEN"),
    }


def _class_share(rows: Sequence[TradeRow], n: int, klass: str) -> float | None:
    if not n:
        return None
    return sum(1 for r in rows if r.quality_class == klass) / n


def _drawdown(net_pnls: Sequence[float], closed_at: Sequence[float]) -> float:
    """Max peak-to-trough of the cell's cumulative net PnL curve, in closed_at order."""
    if not net_pnls:
        return 0.0
    order = sorted(range(len(net_pnls)), key=lambda i: closed_at[i])
    peak = 0.0
    cum = 0.0
    worst = 0.0
    for i in order:
        cum += net_pnls[i]
        peak = max(peak, cum)
        worst = min(worst, cum - peak)     # <= 0
    return worst if worst < 0 else 0.0


def cell_evidence_state(
    trade_count: int, episode_count: int, samples: Sequence[float],
    prior, cfg: ShadowConfig | None = None,
) -> str:
    """UNTESTED/PROVISIONAL/TESTED with the episode-independence gate on top of
    the empirical-Bayes reliability (a cell of one lucky episode is never TESTED)."""
    if trade_count <= 0:
        return UNTESTED
    cfg = cfg or ShadowConfig()
    x = np.clip(np.asarray(samples, dtype=float), *BPS_UNIT.clip)
    result = unit_result(x, prior, BPS_UNIT, cfg, untestable=False)
    if result.state == TESTED and episode_count >= MIN_EPISODES:
        return TESTED
    return PROVISIONAL


def estimate_cell_prior(cell_samples: dict[object, list[float]], cfg: ShadowConfig | None = None):
    """Empirical-Bayes prior over the cells of one (window, granularity) block —
    cells with >= MIN_CELL_TRADES trades inform it, exactly like the agent prior
    in shadow_fitness."""
    cfg = cfg or ShadowConfig()
    by_cell = {k: np.clip(np.asarray(v, dtype=float), *BPS_UNIT.clip) for k, v in cell_samples.items()}
    return estimate_prior(by_cell, BPS_UNIT, cfg)


def cell_bootstrap_inputs(rows: Sequence[TradeRow]) -> dict[int, list[float]]:
    """net pnl grouped by episode — the resampling unit. Trades without an
    episode id are excluded from the bootstrap input (and counted as a finding
    by the store) rather than fabricating independence."""
    grouped: dict[int, list[float]] = {}
    for r in rows:
        if r.episode_id is not None:
            grouped.setdefault(r.episode_id, []).append(r.net_pnl)
    return grouped


def bootstrap_expectancy_ci(rows: Sequence[TradeRow], *, seed_key: tuple[object, ...]) -> tuple[float, float] | None:
    ci = episode_block_bootstrap_ci(cell_bootstrap_inputs(rows), seed_key=seed_key)
    return ci


def edge_flags(
    rows: Sequence[TradeRow], *, seed_key: tuple[object, ...], under_sampled: bool,
) -> tuple[bool, bool]:
    """(gross_edge, net_edge): an edge is declared ONLY when the episode-block
    bootstrap CI of the respective expectancy excludes zero and the cell is not
    under-sampled. Deterministic in the cell identity (seed_key)."""
    if under_sampled or not rows:
        return False, False
    net_grouped: dict[int, list[float]] = {}
    gross_grouped: dict[int, list[float]] = {}
    for r in rows:
        if r.episode_id is not None:
            net_grouped.setdefault(r.episode_id, []).append(r.net_pnl)
            gross_grouped.setdefault(r.episode_id, []).append(r.gross_pnl)
    net_ci = episode_block_bootstrap_ci(net_grouped, seed_key=(*seed_key, "net"))
    gross_ci = episode_block_bootstrap_ci(gross_grouped, seed_key=(*seed_key, "gross"))
    net_edge = net_ci is not None and (net_ci[0] > 0 or net_ci[1] < 0)
    gross_edge = gross_ci is not None and (gross_ci[0] > 0 or gross_ci[1] < 0)
    return gross_edge, net_edge


def under_sampled_flag(trade_count: int, episode_count: int, bootstrap_ok: bool) -> bool:
    """A cell is under-sampled when it cannot support a verdict: fewer than
    MIN_EPISODES episodes (even with many trades — one regime episode is one
    market condition) or no bootstrap CI at all."""
    if trade_count <= 0:
        return True
    return episode_count < MIN_EPISODES or not bootstrap_ok


# cell_metrics keys that edge/expectancy CI needs from elsewhere
GROSS_EXPECTANCY_KEY = "expectancy"


def expectancy_is_significant(ci: tuple[float, float] | None) -> bool:
    return ci is not None and (ci[0] > 0 or ci[1] < 0)