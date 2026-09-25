"""Synthetic ground-truth acceptance tests for the SHADOW fitness (Phase 0).

The true net edge of every agent is known, so these tests judge the proposed architecture on PROPERTIES rather than on
any market sample: it must not reward inaction, must not automatically reject genuinely low-frequency profitable
agents, must not let losing high-frequency agents win, must survive higher costs, and must be reliable split-half.
Deterministic (seeded).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.analytics.shadow_fitness import PROVISIONAL, TESTED, UNTESTED, ShadowAgentInput, compute_shadow, ranked
from tests.helpers_shadow import current_fitness, make_population, with_extra_cost

SEEDS = (101, 202, 303)


def _tested(rows, unit):
    return [r for r in rows if r.unit(unit).state == TESTED]


def _percentile_among_tested(rows, unit, ids):
    """0 = best, 1 = worst rank among TESTED agents, for the given agent ids (ignoring those not TESTED)."""
    order = [r.agent_id for r in ranked(rows, unit)]
    return [order.index(i) / max(1, len(order) - 1) for i in ids if i in order], order


# --------------------------------------------------------------------------- #
# genuinely low-frequency profitable agents are not automatically rejected
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("unit", ["R", "bps"])
def test_low_frequency_profitable_agents_are_not_automatically_rejected(unit):
    tested_share, top_quartile_share = [], []
    for seed in SEEDS:
        # +0.30R edge but only 1.5 trades/day: ~90 trades in 60 days -- a hard 'n >= 100' evidence gate rejects them all
        pop = make_population(seed, n_agents=150, days=60, planted={"lfp": (10, 0.30, 1.5)})
        rows = compute_shadow(pop.agents)
        planted = pop.planted["lfp"]
        assert max(len(pop.agents[i].trades) for i in planted) < 130 and np.mean([len(pop.agents[i].trades) for i in planted]) < 100
        pct, order = _percentile_among_tested(rows, unit, planted)
        tested_share.append(len(pct) / len(planted))
        top_quartile_share.append(np.mean([p <= 0.25 for p in pct]) if pct else 0.0)
    assert np.mean(tested_share) >= 0.8, f"{unit}: low-frequency winners stuck below TESTED ({tested_share})"
    assert np.mean(top_quartile_share) >= 0.5, f"{unit}: low-frequency winners not ranked near the top ({top_quartile_share})"


def test_very_low_frequency_agents_stay_provisional_not_rejected():
    """~30 trades in 60 days is not enough for a RELIABLE estimate: the agent is PROVISIONAL (kept, unranked), never
    UNTESTABLE/penalised, and its posterior has already moved above an untested agent's (the evidence is not thrown away)."""
    for seed in SEEDS:
        pop = make_population(seed, n_agents=150, days=60, planted={"vlf": (10, 0.30, 0.5), "inert": (1, 0.0, 0.0)})
        rows = {r.agent_id: r for r in compute_shadow(pop.agents)}
        inert = rows[pop.planted["inert"][0]]
        assert inert.r.state == UNTESTED
        vlf = [rows[i] for i in pop.planted["vlf"]]
        assert all(r.r.state in (PROVISIONAL, TESTED) for r in vlf)
        assert np.mean([r.r.posterior_mean for r in vlf]) > inert.r.posterior_mean          # inert posterior == the prior


# --------------------------------------------------------------------------- #
# losing high-frequency agents do not automatically win
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("unit", ["R", "bps"])
def test_losing_high_frequency_agents_do_not_win(unit):
    for seed in SEEDS:
        pop = make_population(seed, n_agents=150, days=14, planted={"loser": (10, -0.30, 30.0)})
        rows = compute_shadow(pop.agents)
        pct, order = _percentile_among_tested(rows, unit, pop.planted["loser"])
        assert len(pct) == 10                                                # plenty of evidence: all TESTED
        assert min(pct) > 0.20, f"{unit}: a losing high-frequency agent reached the top 20% ({min(pct):.2f})"
        assert np.median(pct) > 0.60


# --------------------------------------------------------------------------- #
# 2x fees / 3x slippage
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("unit", ["R", "bps"])
def test_ranking_survives_2x_fees_and_3x_slippage(unit):
    """+13 bps per round trip (fees 4.5->9 bps each side, slippage 2->6 bps each side, ~ +13 bps on the round trip)."""
    for seed in SEEDS:
        pop = make_population(seed, n_agents=200, days=14)
        base = compute_shadow(pop.agents)
        stress = compute_shadow([ShadowAgentInput(a.agent_id, with_extra_cost(a.trades, 13.0), a.current_fitness, a.max_drawdown, a.untestable)
                                 for a in pop.agents])
        a = {r.agent_id: r for r in base}; b = {r.agent_id: r for r in stress}
        common = [i for i in a if a[i].unit(unit).state == TESTED and b[i].unit(unit).state == TESTED]
        assert len(common) >= 30
        rho = pd.Series([a[i].unit(unit).proposed_fitness for i in common]).corr(
            pd.Series([b[i].unit(unit).proposed_fitness for i in common]), method="spearman")
        assert rho >= 0.6, f"{unit}: ranking unstable under higher costs (rho={rho:.2f})"
        # stress must never create evidence out of nothing
        assert all(b[i].unit(unit).state == a[i].unit(unit).state for i in a if a[i].unit(unit).state in (UNTESTED, "UNTESTABLE"))
        # and higher costs cannot make the population look better
        assert np.mean([b[i].unit(unit).posterior_mean for i in common]) < np.mean([a[i].unit(unit).posterior_mean for i in common])


# --------------------------------------------------------------------------- #
# split-half reliability
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("unit", ["R", "bps"])
def test_split_half_reliability(unit):
    rhos = []
    for seed in SEEDS:
        pop = make_population(seed, n_agents=200, days=30)
        first = [ShadowAgentInput(a.agent_id, a.trades[: len(a.trades) // 2], a.current_fitness, a.max_drawdown, a.untestable) for a in pop.agents]
        second = [ShadowAgentInput(a.agent_id, a.trades[len(a.trades) // 2:], a.current_fitness, a.max_drawdown, a.untestable) for a in pop.agents]
        A = {r.agent_id: r for r in compute_shadow(first)}; B = {r.agent_id: r for r in compute_shadow(second)}
        common = [i for i in A if A[i].unit(unit).state == TESTED and B[i].unit(unit).state == TESTED]
        assert len(common) >= 20
        rhos.append(pd.Series([A[i].unit(unit).proposed_fitness for i in common]).corr(
            pd.Series([B[i].unit(unit).proposed_fitness for i in common]), method="spearman"))
    assert np.mean(rhos) >= 0.3, f"{unit}: split-half rank correlation too low {rhos}"


# --------------------------------------------------------------------------- #
# ground-truth properties of the ranking itself
# --------------------------------------------------------------------------- #
def _precision(top_ids, truth, thresh=0.1):
    return float(np.mean([truth[i] >= thresh for i in top_ids])) if len(top_ids) else float("nan")


def _current_top(pop, k):
    live = [a for a in pop.agents if not a.untestable]
    return [a.agent_id for a in sorted(live, key=lambda a: a.current_fitness, reverse=True)[:k]]


def test_ranking_identifies_real_edge_in_a_mixed_world():
    lifts = []
    for seed in SEEDS:
        pop = make_population(seed, n_agents=300, days=14)
        rows = compute_shadow(pop.agents)
        top = [r.agent_id for r in ranked(rows, "R", top=40)]
        base_rate = np.mean([pop.truth_edge[r.agent_id] >= 0.1 for r in _tested(rows, "R")])
        lifts.append(_precision(top, pop.truth_edge) - base_rate)
    assert np.mean(lifts) > 0.15, f"top of the shadow ranking is not enriched in true winners ({lifts})"


def _lfp_world_precisions(include_provisional):
    shadow_p, current_p, gate_p = [], [], []
    for seed in SEEDS:
        pop = make_population(seed, n_agents=300, days=30, low_freq_winners=True)
        rows = compute_shadow(pop.agents)
        k = 40
        shadow_p.append(_precision([r.agent_id for r in ranked(rows, "R", top=k, include_provisional=include_provisional)], pop.truth_edge))
        current_p.append(_precision(_current_top(pop, k), pop.truth_edge))
        # the naive alternative: hard gate n >= 100 trades, then rank by raw mean R
        gated = sorted((r for r in rows if r.r.state != "UNTESTABLE" and r.r.n >= 100), key=lambda r: r.r.mean, reverse=True)[:k]
        gate_p.append(_precision([r.agent_id for r in gated], pop.truth_edge))
    return shadow_p, current_p, gate_p


def test_shadow_ranking_including_provisional_is_not_worse_than_current_when_good_strategies_are_low_frequency():
    """The world hard evidence gates fail in (and the one the user asked about: 'A' must not be eliminated)."""
    shadow_p, current_p, gate_p = _lfp_world_precisions(include_provisional=True)
    assert np.mean(shadow_p) >= np.mean(current_p) - 0.02, (shadow_p, current_p)
    assert np.mean(shadow_p) > np.mean(gate_p) + 0.2, (shadow_p, gate_p)   # a hard count gate discriminates against low-frequency winners


@pytest.mark.xfail(strict=True, reason="KNOWN FAILURE CASE: ranking TESTED agents only is a soft evidence gate; genuinely low-frequency "
                   "winners stay PROVISIONAL and are never ranked (precision ~0.06 vs current ~0.36). Both policies are reported in shadow.")
def test_ranking_tested_only_is_not_worse_than_current_when_good_strategies_are_low_frequency():
    shadow_p, current_p, _ = _lfp_world_precisions(include_provisional=False)
    assert np.mean(shadow_p) >= np.mean(current_p) - 0.02, (shadow_p, current_p)


def test_selection_in_a_null_world_is_not_worse_than_the_population():
    for seed in SEEDS:
        pop = make_population(seed, n_agents=300, days=14, world="null")
        rows = compute_shadow(pop.agents)
        top = [r.agent_id for r in ranked(rows, "R", top=40)]
        assert np.mean([pop.truth_edge[i] for i in top]) >= np.mean([pop.truth_edge[r.agent_id] for r in _tested(rows, "R")]) - 0.02


@pytest.mark.xfail(strict=True, reason="KNOWN FAILURE CASE: with the specified 0.80 posterior-probability rule, ~1.6 zero-edge agents per "
                   "300-agent generation obtain 'champion evidence' by chance (multiple comparisons). See the threshold test below.")
def test_no_champion_evidence_is_manufactured_in_a_null_world_at_the_default_threshold():
    from app.analytics.shadow_fitness import champion_evidence_ok

    for seed in range(10):
        rows = compute_shadow(make_population(seed, n_agents=300, days=14, world="null").agents)
        assert not any(champion_evidence_ok(r.r) or champion_evidence_ok(r.bps) for r in rows)


def test_champion_false_positives_fall_with_the_threshold_and_vanish_at_0_99():
    from app.analytics.shadow_fitness import ShadowConfig, champion_evidence_ok

    def flagged(th):
        cfg, total = ShadowConfig(champion_probability=th), 0
        for seed in range(12):
            rows = compute_shadow(make_population(seed, n_agents=300, days=14, world="null").agents, cfg)
            total += sum(champion_evidence_ok(r.r, cfg) or champion_evidence_ok(r.bps, cfg) for r in rows)
        return total
    f80, f95, f99 = flagged(0.80), flagged(0.95), flagged(0.99)
    assert f80 > f95 >= f99 and f99 == 0, (f80, f95, f99)


def test_current_fitness_can_be_computed_on_the_same_synthetic_data():
    trades = make_population(7, n_agents=5, days=14).agents[0].trades
    f, dd = current_fitness(trades, 14)
    assert isinstance(f, float) and 0.0 <= dd <= 1.0
