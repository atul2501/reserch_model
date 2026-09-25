"""Synthetic ground-truth generator for the shadow-fitness tests.

The TRUE net edge of every synthetic agent is known (in R per trade, after all costs), so a fitness design can be
judged on what it is for: identifying real edge, not rewarding inaction, and being fair across trade frequencies.
Everything is seeded and deterministic. Nothing here touches the database or any production module.
"""
from __future__ import annotations

import math
import types

import numpy as np

from app.analytics.fitness_engine import FitnessInputs, FitnessWeights, compute_fitness
from app.analytics.performance_metrics_engine import compute_trade_stats
from app.analytics.shadow_fitness import ShadowAgentInput, TradeEvidence
from app.research.lockbox import compute_oos_score

STOP_BPS = 13.0          # typical stop distance in bps of notional (median in the real replay)
START = 100.0


def make_trades(rng, edge_r: float, lam: float, days: float, *, sigma: float = 1.0, notional_scale: float = 20.0,
                stop_bps_scale: float = STOP_BPS, extra_cost_bps: float = 0.0) -> list[TradeEvidence]:
    """Poisson(lam*days) trades with true mean net return `edge_r` (in R), heavy-tailed (t4) noise, per-trade stop
    distance and notional. Net P&L = R * risk - optional extra cost in bps of notional."""
    n = int(rng.poisson(lam * days))
    x = edge_r + sigma * rng.standard_t(4, n) / math.sqrt(2.0)
    stop_bps = stop_bps_scale * np.exp(rng.normal(0.0, 0.5, n))
    notional = notional_scale * np.exp(rng.normal(0.0, 0.3, n))
    risk = notional * stop_bps / 1e4
    pnl = x * risk - notional * extra_cost_bps / 1e4
    return [TradeEvidence(net_pnl=float(p), notional=float(nt), risk=float(r)) for p, nt, r in zip(pnl, notional, risk)]


def with_extra_cost(trades: list[TradeEvidence], bps: float) -> list[TradeEvidence]:
    """The SAME trades under higher costs (2x fees + 3x slippage is roughly +13 bps per round trip)."""
    return [TradeEvidence(t.net_pnl - t.notional * bps / 1e4, t.notional, t.risk) for t in trades]


def scaled(trades: list[TradeEvidence], k: float) -> list[TradeEvidence]:
    """Pure exposure scaling: k times the size, identical trading decisions."""
    return [TradeEvidence(t.net_pnl * k, t.notional * k, t.risk * k) for t in trades]


def _fake_backtest(pnls: np.ndarray):
    cum = START + np.cumsum(pnls)
    peak = np.maximum.accumulate(np.r_[START, cum])[1:] if len(pnls) else np.array([START])
    dd = float(((peak - cum) / peak).max()) if len(pnls) else 0.0
    gw, gl = pnls[pnls > 0].sum(), -pnls[pnls < 0].sum()
    pf = (gw / gl) if gl > 0 else (float("inf") if gw > 0 else None)
    return types.SimpleNamespace(trades=list(pnls), profit_factor=pf, net_return_pct=float(pnls.sum() / START), max_drawdown_pct=dd)


def current_fitness(trades: list[TradeEvidence], days: float) -> tuple[float, float]:
    """(production compute_fitness, max drawdown) fed the way fitness_service feeds it: paper stats + a validation slice
    (last 25% of the trades) + walk-forward consistency (share of profitable windows) + the UNSTABLE/no-trade regime."""
    pnl = np.array([t.net_pnl for t in trades], dtype=float)
    n = len(pnl)
    st = compute_trade_stats(list(pnl), [0] * n)
    bt = _fake_backtest(pnl)
    val = compute_oos_score(_fake_backtest(pnl[int(n * 0.75):]), min_trades=3)
    k = int(min(8, max(2, round(0.6 * days))))
    chunks = np.array_split(pnl, k)
    wfo = sum(1 for c in chunks if len(c) and c.sum() > 0) / k
    fi = FitnessInputs(
        net_return_pct=float(pnl.sum() / START), profit_factor=st.profit_factor, max_drawdown_pct=bt.max_drawdown_pct,
        expectancy=st.expectancy, trade_count=n, win_rate=st.win_rate, survival_days=days, sharpe_like=st.sharpe_like,
        oos_score=val, walk_forward_score=wfo, return_volatility=abs(st.return_volatility / START) if st.return_volatility else None,
        regime_robustness=0.1, starting_balance=START)
    return compute_fitness(fi, FitnessWeights.from_settings()).fitness, bt.max_drawdown_pct


class Population:
    """Agents plus the ground truth. `truth_edge[i]` is the true net edge (R/trade) of agent i."""

    def __init__(self, agents: list[ShadowAgentInput], truth_edge: np.ndarray, lam: np.ndarray, planted: dict[str, list[int]]):
        self.agents, self.truth_edge, self.lam, self.planted = agents, truth_edge, lam, planted


def make_population(seed: int, *, n_agents: int = 300, days: float = 14.0, world: str = "mixed",
                    untestable_share: float = 0.30, low_freq_winners: bool = False, planted: dict | None = None) -> Population:
    """world 'mixed': edges {-0.30,-0.10,0,+0.12,+0.30} with weights .42/.25/.15/.10/.08; 'null': no positive edge.
    Frequencies are log-uniform in [0.3, 40] trades/day and INDEPENDENT of edge unless `low_freq_winners` (then good
    strategies are the selective, low-frequency ones). `planted` = {label: (count, edge, lam)} extra agents."""
    rng = np.random.default_rng(seed)
    if world == "null":
        edges = rng.choice([-0.30, -0.10, 0.0], size=n_agents, p=[.5, .3, .2])
    else:
        edges = rng.choice([-0.30, -0.10, 0.0, 0.12, 0.30], size=n_agents, p=[.42, .25, .15, .10, .08])
    lam = np.exp(rng.uniform(math.log(0.3), math.log(40.0), n_agents))
    if low_freq_winners:
        order = np.argsort(np.argsort(edges + rng.normal(0, 1e-6, n_agents)))       # rank of edge
        lam = np.sort(lam)[::-1][order] * np.exp(rng.normal(0, 0.35, n_agents))
    untestable = rng.random(n_agents) < untestable_share
    agents, truth, lams = [], list(edges), list(lam)
    for i in range(n_agents):
        tr = make_trades(rng, edges[i], lam[i], days)
        cf, dd = current_fitness(tr, days)
        agents.append(ShadowAgentInput(agent_id=i, trades=tr, current_fitness=cf, max_drawdown=dd, untestable=bool(untestable[i])))
    labels: dict[str, list[int]] = {}
    for label, (count, edge, l) in (planted or {}).items():
        labels[label] = []
        for _ in range(count):
            i = len(agents)
            tr = make_trades(rng, edge, l, days)
            cf, dd = current_fitness(tr, days)
            agents.append(ShadowAgentInput(agent_id=i, trades=tr, current_fitness=cf, max_drawdown=dd))
            truth.append(edge); lams.append(l); labels[label].append(i)
    return Population(agents, np.array(truth), np.array(lams), labels)
