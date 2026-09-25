"""SHADOW evaluation of the proposed evidence-aware fitness architecture (Phase 0).

THIS MODULE MUST NOT INFLUENCE ANYTHING. `Agent.fitness` (fitness_engine.compute_fitness) stays the only production
score. Nothing here is imported by survivor selection, breeding, mutation, champion selection, agent death or status
(tests/test_shadow_fitness.py enforces that by inspecting those modules), and the DB service only SELECTs.

Proposal under evaluation, per agent and per candidate UNIT (R and bps are kept SEPARATE; no primary unit is chosen):

    x_t      net return of trade t after fees, slippage and funding
             R   : net_pnl / risk_at_stop          (risk = quantity * |entry - stop|; scale-free in exposure)
             bps : 1e4 * net_pnl / notional        (notional = quantity * entry_price; scale-free in exposure)
    m, s2    sample mean and (stabilised) variance of x_t over the agent's n trades
    mu0,tau2 population prior, estimated from the generation itself (empirical Bayes, NO hand-tuned edge)
    m*       = (n*m/s2 + mu0/tau2) / (n/s2 + 1/tau2)          posterior mean of the agent's true net edge
    v*       = 1 / (n/s2 + 1/tau2)                              posterior variance
    rel      = tau2 / (tau2 + s2/n)                             reliability of the estimate (0 with no trades)

Evidence state:  UNTESTABLE (cannot reach the exchange minimum, Option D)  >  UNTESTED (feasible, no trades)
                 > PROVISIONAL (0 < rel < tested_reliability)  >  TESTED (rel >= tested_reliability).
proposed_fitness = m* whenever the agent has evidence (PROVISIONAL or TESTED) and None for UNTESTED/UNTESTABLE: an
agent with no evidence is neither penalised nor rewarded, it is simply not ranked. WHICH states may be ranked is an
explicit policy (`ranked(..., include_provisional=...)`): ranking TESTED only is a soft evidence gate and, in the
synthetic ground-truth study, discriminates against genuinely low-frequency winners (whose evidence stays PROVISIONAL);
both policies are evaluated in shadow. No hierarchical family prior yet (deliberately).
"""
from __future__ import annotations

import math
import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

UNTESTABLE = "UNTESTABLE"
UNTESTED = "UNTESTED"
PROVISIONAL = "PROVISIONAL"
TESTED = "TESTED"
STATES = (UNTESTABLE, UNTESTED, PROVISIONAL, TESTED)


@dataclass(frozen=True)
class UnitConfig:
    name: str
    clip: tuple[float, float]      # winsorisation of a single trade's return (a gap loss must not dominate an agent)
    s_min: float                   # variance floor (a handful of identical trades must not look risk-free)
    tau_min: float                 # floor on the between-agent dispersion of true edge
    fallback_tau2: float           # prior variance when too few agents are informative to estimate one


R_UNIT = UnitConfig("R", (-6.0, 6.0), 0.5, 0.10, 0.25)
BPS_UNIT = UnitConfig("bps", (-200.0, 200.0), 10.0, 2.0, 100.0)
UNITS = {"R": R_UNIT, "bps": BPS_UNIT}


@dataclass(frozen=True)
class ShadowConfig:
    prior_min_trades: int = 10          # an agent informs the population prior only with at least this many trades
    min_prior_agents: int = 5           # fewer informative agents -> weakly informative fallback prior
    tested_reliability: float = 0.5     # TESTED once the estimate is at least half signal
    variance_prior_trades: float = 4.0  # pseudo-observations pulling a small-n variance toward the population's
    champion_probability: float = 0.80  # P(true edge > 0) required for shadow champion evidence
    champion_min_trades: int = 30       # statistical floor for a normal approximation
    # How the between-agent dispersion tau2 is estimated. "mad" (default) is robust to a few lucky short-streak agents but
    # treats a MINORITY of genuine winners as outliers (tau2 collapses, winners are shrunk away); "var" keeps them but lets
    # outliers inflate tau2. Both are kept for shadow diagnosis; neither is chosen (see the Phase 0 report).
    tau_estimator: str = "mad"


@dataclass(frozen=True)
class TradeEvidence:
    net_pnl: float
    notional: float
    risk: float = float("nan")          # quantity * |entry - stop|; NaN/0 when the stop is unknown

    @property
    def net_bps(self) -> float | None:
        return 1e4 * self.net_pnl / self.notional if self.notional > 0 else None

    @property
    def net_r(self) -> float | None:
        return self.net_pnl / self.risk if self.risk == self.risk and self.risk > 0 else None


@dataclass
class ShadowAgentInput:
    agent_id: object
    trades: Sequence[TradeEvidence]
    current_fitness: float | None
    max_drawdown: float = 0.0
    untestable: bool = False
    family: str | None = None


@dataclass(frozen=True)
class Prior:
    mu0: float
    tau2: float
    s2_pool: float
    informative_agents: int
    fallback: bool


@dataclass
class UnitResult:
    unit: str
    n: int
    mean: float | None
    posterior_mean: float | None
    posterior_variance: float | None
    reliability: float
    state: str
    proposed_fitness: float | None
    p_edge_positive: float | None


@dataclass
class ShadowRow:
    agent_id: object
    family: str | None
    current_fitness: float | None
    trade_count: int
    net_pnl: float
    net_bps: float | None            # pooled: 1e4 * sum(pnl) / sum(notional)
    mean_r: float | None
    drawdown: float
    expectancy: float | None         # mean net P&L per trade, account currency
    r: UnitResult = field(default=None)      # type: ignore[assignment]
    bps: UnitResult = field(default=None)    # type: ignore[assignment]

    def unit(self, name: str) -> UnitResult:
        return self.r if name == "R" else self.bps


# --------------------------------------------------------------------------- #
# statistics
# --------------------------------------------------------------------------- #
def _samples(trades: Sequence[TradeEvidence], unit: UnitConfig) -> np.ndarray:
    getter = (lambda t: t.net_r) if unit.name == "R" else (lambda t: t.net_bps)
    vals = [getter(t) for t in trades]
    return np.clip(np.array([v for v in vals if v is not None], dtype=float), *unit.clip)


def estimate_prior(samples_by_agent: dict[object, np.ndarray], unit: UnitConfig, cfg: ShadowConfig) -> Prior:
    """Empirical-Bayes population prior from the agents that traded enough to inform it (untestable agents excluded
    by the caller). mu0 = median of the agents' means; tau2 = observed variance of means minus their sampling noise."""
    means, se2, s2 = [], [], []
    for x in samples_by_agent.values():
        if len(x) >= cfg.prior_min_trades:
            var = max(float(x.var(ddof=1)), unit.s_min ** 2)
            means.append(float(x.mean()))
            se2.append(var / len(x))
            s2.append(var)
    if len(means) < cfg.min_prior_agents:
        return Prior(0.0, unit.fallback_tau2, unit.s_min ** 2, len(means), True)
    m = np.array(means)
    # ROBUST dispersion (MAD): a few lucky short-streak agents must not inflate tau2, which would weaken the shrinkage
    # of every other agent (found by tests/test_shadow_fitness.py::test_lucky_short_streak_*: var() let two lucky
    # agents promote an 8-trade streak to TESTED).
    if cfg.tau_estimator == "var":
        tau2 = max(unit.tau_min ** 2, float(m.var(ddof=1)) - float(np.mean(se2)))
    else:
        mad = float(np.median(np.abs(m - np.median(m)))) * 1.4826
        tau2 = max(unit.tau_min ** 2, mad ** 2 - float(np.median(se2)))
    return Prior(float(np.median(m)), tau2, float(np.median(s2)), len(means), False)


def unit_result(x: np.ndarray, prior: Prior, unit: UnitConfig, cfg: ShadowConfig, *, untestable: bool) -> UnitResult:
    n = len(x)
    if untestable:
        return UnitResult(unit.name, n, float(x.mean()) if n else None, None, None, 0.0, UNTESTABLE, None, None)
    if n == 0:
        return UnitResult(unit.name, 0, None, prior.mu0, prior.tau2, 0.0, UNTESTED, None, None)
    m = float(x.mean())
    var = float(x.var(ddof=1)) if n > 1 else prior.s2_pool
    nu = cfg.variance_prior_trades
    s2 = max((nu * prior.s2_pool + (n - 1) * var) / (nu + n - 1), unit.s_min ** 2)   # stabilised small-n variance
    precision = n / s2 + 1.0 / prior.tau2
    post_mean = (n * m / s2 + prior.mu0 / prior.tau2) / precision
    post_var = 1.0 / precision
    reliability = prior.tau2 / (prior.tau2 + s2 / n)
    state = TESTED if reliability >= cfg.tested_reliability else PROVISIONAL
    p_pos = 0.5 * math.erfc(-(post_mean / math.sqrt(post_var)) / math.sqrt(2.0))
    return UnitResult(unit.name, n, m, post_mean, post_var, reliability, state, post_mean, p_pos)


def compute_shadow(agents: Iterable[ShadowAgentInput], cfg: ShadowConfig | None = None) -> list[ShadowRow]:
    """Pure function: side-by-side rows for every agent. Priors are estimated per unit from the non-untestable agents
    of THIS call (i.e. one generation)."""
    cfg = cfg or ShadowConfig()
    agents = list(agents)
    per_unit = {name: {a.agent_id: _samples(a.trades, u) for a in agents} for name, u in UNITS.items()}
    priors = {name: estimate_prior({a.agent_id: per_unit[name][a.agent_id] for a in agents if not a.untestable}, u, cfg)
              for name, u in UNITS.items()}
    rows: list[ShadowRow] = []
    for a in agents:
        pnls = [t.net_pnl for t in a.trades]
        notional = sum(t.notional for t in a.trades)
        rs = _samples(a.trades, R_UNIT)
        row = ShadowRow(
            agent_id=a.agent_id, family=a.family, current_fitness=a.current_fitness, trade_count=len(a.trades),
            net_pnl=float(sum(pnls)), net_bps=(1e4 * sum(pnls) / notional) if notional > 0 else None,
            mean_r=float(rs.mean()) if len(rs) else None, drawdown=a.max_drawdown,
            expectancy=(float(np.mean(pnls)) if pnls else None),
        )
        row.r = unit_result(per_unit["R"][a.agent_id], priors["R"], R_UNIT, cfg, untestable=a.untestable)
        row.bps = unit_result(per_unit["bps"][a.agent_id], priors["bps"], BPS_UNIT, cfg, untestable=a.untestable)
        rows.append(row)
    return rows


# --------------------------------------------------------------------------- #
# comparison helpers (report only)
# --------------------------------------------------------------------------- #
def ranked(rows: Sequence[ShadowRow], score: str, *, top: int | None = None, include_provisional: bool = False) -> list[ShadowRow]:
    """Rows ordered best-first by 'current', 'R' or 'bps'. Proposed scores rank TESTED agents only by default;
    `include_provisional=True` also ranks PROVISIONAL agents (UNTESTED and UNTESTABLE are never ranked)."""
    def key(r: ShadowRow):
        if score == "current":
            # mirrors production selection, which excludes untestable agents (Option D)
            return None if r.r.state == UNTESTABLE else r.current_fitness
        u = r.unit(score)
        return u.proposed_fitness if u.state == TESTED or (include_provisional and u.state == PROVISIONAL) else None
    out = sorted((r for r in rows if key(r) is not None), key=key, reverse=True)
    return out[:top] if top else out


def rank_correlation(rows: Sequence[ShadowRow], a: str, b: str, *, include_provisional: bool = False) -> tuple[float | None, int]:
    """Spearman rank correlation between two scores over the agents that are ranked under BOTH. Returns (rho, n)."""
    def key(r: ShadowRow, s: str):
        if s == "current":
            return None if r.r.state == UNTESTABLE else r.current_fitness
        u = r.unit(s)
        return u.proposed_fitness if u.state == TESTED or (include_provisional and u.state == PROVISIONAL) else None
    pairs = [(key(r, a), key(r, b)) for r in rows if key(r, a) is not None and key(r, b) is not None]
    if len(pairs) < 3:
        return None, len(pairs)
    x = pd.Series([p[0] for p in pairs]).rank()
    y = pd.Series([p[1] for p in pairs]).rank()
    rho = float(x.corr(y))
    return (None if rho != rho else rho), len(pairs)


def champion_evidence_ok(result: UnitResult, cfg: ShadowConfig | None = None) -> bool:
    """SHADOW-ONLY champion evidence: the posterior must show a positive true edge with probability >= 0.80 on a
    TESTED estimate with at least `champion_min_trades` trades. A lucky short streak cannot pass it: its estimate is
    PROVISIONAL and its posterior stays pinned near the (typically negative) population prior. This does NOT gate any
    real promotion."""
    cfg = cfg or ShadowConfig()
    return (result.state == TESTED and result.n >= cfg.champion_min_trades
            and result.p_edge_positive is not None and result.p_edge_positive >= cfg.champion_probability)


# --------------------------------------------------------------------------- #
# read-only DB service
# --------------------------------------------------------------------------- #
async def shadow_rows_for_generation(db, generation: int, cfg: ShadowConfig | None = None) -> list[ShadowRow]:
    """Side-by-side shadow rows for every agent of `generation`, built from persisted rows. SELECT only: it writes
    nothing, changes no status and never touches `Agent.fitness` (which is read as `current_fitness`).

    R needs each trade's risk at the stop: quantity * |entry_price - Position.stop_loss_price| (the position keeps its
    stop after it closes). No schema change."""
    from sqlalchemy import select

    from app.agents.tradability import untestable_agent_ids
    from app.models.agent import Agent
    from app.models.strategy import Strategy, StrategyVersion
    from app.models.trading import Position, Trade

    agents = (await db.execute(select(Agent).where(Agent.generation == generation))).scalars().all()
    if not agents:
        return []
    ids = [a.id for a in agents]
    family_by_version = {
        vid: fam.value for vid, fam in (await db.execute(
            select(StrategyVersion.id, Strategy.family).join(Strategy, Strategy.id == StrategyVersion.strategy_id)
            .where(StrategyVersion.id.in_({a.strategy_version_id for a in agents}))
        )).all() if fam is not None
    }
    by_agent: dict[uuid.UUID, list[TradeEvidence]] = defaultdict(list)
    for t, stop in (await db.execute(
        select(Trade, Position.stop_loss_price).join(Position, Position.id == Trade.position_id)
        .where(Trade.agent_id.in_(ids)).order_by(Trade.closed_at)
    )).all():
        risk = t.quantity * abs(t.entry_price - stop) if stop is not None else float("nan")
        by_agent[t.agent_id].append(TradeEvidence(net_pnl=t.net_pnl, notional=t.quantity * t.entry_price, risk=risk))
    untestable = await untestable_agent_ids(db, agents)
    return compute_shadow(
        (ShadowAgentInput(agent_id=a.id, trades=by_agent.get(a.id, []), current_fitness=a.fitness,
                          max_drawdown=a.max_drawdown, untestable=a.id in untestable,
                          family=family_by_version.get(a.strategy_version_id))
         for a in agents), cfg,
    )
