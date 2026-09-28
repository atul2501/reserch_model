"""Regression coverage for app.analytics.fitness_versions and the fitness_forward.py extensions
it relies on (oos_window_ms, return_transform). Research-only infrastructure: these tests exist to
prove (a) v1 is frozen to today's real production weights, (b) the OOS-window exclusion and the
"not yet closed by as_of" exclusion are genuinely different code paths that are never conflated,
and (c) nothing here is reachable from any production module.
"""
from __future__ import annotations

import importlib
import inspect
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.analytics.fitness_engine import FitnessWeights
from app.analytics.fitness_forward import AgentFacts, TradePoint, forward_performance, forward_window, reconstruct_fitness_at
from app.analytics.fitness_versions import (
    EVIDENCE_MODE_LATER_ASOF, EVIDENCE_MODE_PRODUCTION, FITNESS_VERSIONS, _v1_weights,
)
from app.models.enums import AgentStatus

T0 = datetime(2026, 9, 27, 0, 0, 0, tzinfo=timezone.utc)


def _facts(**overrides) -> AgentFacts:
    base = dict(agent_id=uuid.uuid4(), generation=1, starting_balance=100.0, created_at=T0, death_timestamp=None, status=AgentStatus.ACTIVE)
    base.update(overrides)
    return AgentFacts(**base)


def _trade(opened_at: datetime, closed_at: datetime, net_pnl: float = 1.0, notional: float = 100.0) -> TradePoint:
    return TradePoint(closed_at=closed_at, net_pnl=net_pnl, notional=notional, opened_at=opened_at)


# --------------------------------------------------------------------------- #
# 1. v1 is frozen to TODAY's real production weights
# --------------------------------------------------------------------------- #
def test_v1_weights_match_production_settings():
    """If this fails, production's FITNESS_W_* config has moved and "v1" needs a conscious
    decision about whether to follow it - never a silent drift."""
    from_settings = FitnessWeights.from_settings()
    assert FITNESS_VERSIONS["v1"].weights == from_settings
    assert _v1_weights() == from_settings


def test_v1_and_v1_timing_fix_share_identical_weights():
    """The ONLY difference between v1 and v1_timing_fix is evidence_mode (which as_of the
    evaluator tries), never the formula."""
    assert FITNESS_VERSIONS["v1"].weights == FITNESS_VERSIONS["v1_timing_fix"].weights


def test_every_registered_version_uses_a_known_evidence_mode():
    """Guards against a future edit silently introducing an unprotected mode: every version must
    be one of the two modes that ALWAYS pass oos_window_ms through when reconstructed - there is
    no registry-level way to skip OOS protection."""
    for spec in FITNESS_VERSIONS.values():
        assert spec.evidence_mode in (EVIDENCE_MODE_PRODUCTION, EVIDENCE_MODE_LATER_ASOF)


# --------------------------------------------------------------------------- #
# 2. as_of boundary: reconstruct_fitness_at never sees a trade closed after as_of
# --------------------------------------------------------------------------- #
def test_reconstruct_fitness_at_excludes_trade_closed_after_as_of():
    facts = _facts()
    as_of = T0 + timedelta(hours=1)
    trades = [
        _trade(T0, T0 + timedelta(minutes=30)),               # closes before as_of: visible
        _trade(T0 + timedelta(minutes=50), as_of),             # closes exactly at as_of: visible
        _trade(as_of + timedelta(milliseconds=1), as_of + timedelta(minutes=5)),  # after as_of: must never be seen
    ]
    recon = reconstruct_fitness_at(facts, trades, as_of=as_of, weights=_v1_weights())
    assert recon.components["trade_count"] == 2


# --------------------------------------------------------------------------- #
# 3. forward_performance: window_start is exclusive
# --------------------------------------------------------------------------- #
def test_forward_performance_excludes_trade_at_or_before_window_start():
    as_of = T0
    window = forward_window(as_of, 60, death_at=None, generation_rollover_at=None, data_end=as_of + timedelta(hours=2))
    trades = [
        _trade(T0 - timedelta(minutes=5), as_of, net_pnl=5.0),                    # closes exactly at window_start: excluded
        _trade(as_of + timedelta(minutes=1), as_of + timedelta(minutes=2), net_pnl=7.0),  # inside window: included
    ]
    perf = forward_performance(trades, window, starting_balance=100.0)
    assert perf.trade_count == 1
    assert perf.net_pnl == 7.0


# --------------------------------------------------------------------------- #
# 4. Hard OOS-protection invariant: the two exclusion reasons are genuinely different code paths
# --------------------------------------------------------------------------- #
def test_oos_window_exclusion_is_distinct_from_as_of_availability():
    """Constructs three trades:
      - trade A: closed before as_of, entirely OUTSIDE the OOS window -> counted under both v1 and v1_timing_fix
      - trade B: closed before as_of, but its lifetime OVERLAPS the sealed OOS window -> must NEVER be counted
                 by either v1 or v1_timing_fix, regardless of as_of
      - trade C: closed AFTER v1's original as_of but BEFORE a later as_of, also outside the OOS window ->
                 invisible to v1 (not yet closed), visible to v1_timing_fix (later as_of, no OOS overlap)
    This is the exact distinction the plan requires: v1_timing_fix adds trade C (category b: not-yet-closed)
    without ever touching trade B (category a: OOS-protected).
    """
    facts = _facts()
    oos_start = T0 + timedelta(hours=2)
    oos_end = T0 + timedelta(hours=4)
    oos_window_ms = (int(oos_start.timestamp() * 1000), int(oos_end.timestamp() * 1000))

    trade_a = _trade(T0, T0 + timedelta(minutes=30))                                    # clean, non-OOS
    trade_b = _trade(oos_start + timedelta(minutes=10), oos_start + timedelta(minutes=20))  # inside OOS window
    trade_c = _trade(T0 + timedelta(hours=5), T0 + timedelta(hours=5, minutes=10))        # after OOS end, later trade

    original_as_of = T0 + timedelta(hours=1)      # what "production" would have used: only trade_a exists yet
    later_as_of = T0 + timedelta(hours=6)          # v1_timing_fix: trade_c has since closed

    trades = [trade_a, trade_b, trade_c]

    v1_recon = reconstruct_fitness_at(facts, trades, as_of=original_as_of, weights=_v1_weights(), oos_window_ms=oos_window_ms)
    assert v1_recon.components["trade_count"] == 1   # only trade_a: trade_b is OOS, trade_c hasn't closed yet

    timing_fix_recon = reconstruct_fitness_at(facts, trades, as_of=later_as_of, weights=_v1_weights(), oos_window_ms=oos_window_ms)
    assert timing_fix_recon.components["trade_count"] == 2   # trade_a AND trade_c now - trade_b STILL excluded

    # Trade B must never appear in either, no matter how far as_of moves - that's the hard invariant.
    far_future_recon = reconstruct_fitness_at(facts, trades, as_of=T0 + timedelta(days=30), weights=_v1_weights(), oos_window_ms=oos_window_ms)
    assert far_future_recon.components["trade_count"] == 2, "OOS-overlapping trade must never be counted, at any as_of"


def test_without_oos_window_ms_behavior_is_unchanged_default():
    """oos_window_ms=None (the default, used by the existing production writer
    refresh_fitness_forward) must reproduce exactly today's behavior: no OOS awareness at all."""
    facts = _facts()
    oos_start = T0 + timedelta(hours=2)
    oos_end = T0 + timedelta(hours=4)
    trade_inside_oos = _trade(oos_start + timedelta(minutes=10), oos_start + timedelta(minutes=20))
    as_of = T0 + timedelta(hours=5)

    recon = reconstruct_fitness_at(facts, [trade_inside_oos], as_of=as_of, weights=_v1_weights())  # no oos_window_ms
    assert recon.components["trade_count"] == 1   # visible: OOS-blind by default, matches pre-existing behavior


# --------------------------------------------------------------------------- #
# 5. return_transform patches only the return_score term
# --------------------------------------------------------------------------- #
def test_return_transform_changes_only_return_score_component():
    facts = _facts()
    as_of = T0 + timedelta(hours=1)
    trades = [_trade(T0, T0 + timedelta(minutes=10), net_pnl=50.0) for _ in range(30)]  # full sample_confidence

    baseline = reconstruct_fitness_at(facts, trades, as_of=as_of, weights=_v1_weights())
    transformed = reconstruct_fitness_at(facts, trades, as_of=as_of, weights=_v1_weights(), return_transform=lambda x: 0.0)

    assert transformed.components["return_score"] == 0.0
    assert baseline.components["return_score"] != 0.0
    # every OTHER component must be identical - only return_score (and the fitness total it feeds) changed
    for key in ("risk_score", "consistency_score", "oos_score", "drawdown_penalty", "trade_count"):
        assert baseline.components[key] == transformed.components[key]


# --------------------------------------------------------------------------- #
# 6. isolation: nothing in production ever imports this research-only module
# --------------------------------------------------------------------------- #
PRODUCTION_MODULES = [
    "app.evolution.breeding", "app.evolution.champion", "app.evolution.promotion_service",
    "app.evolution.champion_challenger_service", "app.evolution.mutation", "app.evolution.crossover",
    "app.evolution.diversity", "app.analytics.fitness_engine", "app.analytics.fitness_service",
    "app.agents.lifecycle", "app.agents.decision_loop", "app.agents.position_manager", "app.research.pipeline",
    "app.worker.cycle", "app.execution.router",
]


@pytest.mark.parametrize("module", PRODUCTION_MODULES)
def test_production_modules_never_import_fitness_versions(module):
    src = inspect.getsource(importlib.import_module(module))
    assert "fitness_versions" not in src, f"{module} must not depend on the research-only fitness_versions registry"


def test_fitness_versions_module_has_no_write_path():
    import app.analytics.fitness_versions as fv

    src = inspect.getsource(fv)
    for forbidden in (".add(", ".commit(", ".flush(", ".delete(", "AgentStatus", "mark_dead"):
        assert forbidden not in src, f"fitness_versions.py must stay a pure spec registry ({forbidden})"
