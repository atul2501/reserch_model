"""Research-only registry of named fitness formula/timing variants for offline evaluation
(scripts/evaluate_fitness_versions.py). NOTHING here is imported by any production module -
enforced by tests/test_fitness_versions.py's isolation guard, same pattern as shadow_fitness.py.

Every version protects the sealed OOS holdout identically (oos_window_ms is always applied when
reconstructing under any of these specs) - v1 and v1_timing_fix differ ONLY in which `as_of` the
caller evaluates at, never in whether OOS-overlapping trades are visible. See fitness_forward.py's
reconstruct_fitness_at docstring for the (a) OOS-excluded vs (b) not-yet-closed-by-as_of distinction
this registry deliberately keeps separate. Whether the OOS-window exclusion itself should be relaxed
for the fitness signal (as opposed to the promotion signal, which must never see it) is treated here
as an explicit, unresolved hypothesis (H0/H1) - this registry does not take a side on it; the offline
evaluator's job is to produce evidence, not to assume the outcome.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, replace

from app.analytics.fitness_engine import FitnessWeights

# "production" -> evaluate only at the as_of production actually used historically.
# "production_later_asof" -> evaluate across the reconstruction grid (later as_of values),
# using more non-OOS evidence that has since become available. Both modes always pass
# oos_window_ms through to reconstruct_fitness_at; this flag steers which as_of points the
# evaluator tries for this version, it never changes what counts as OOS-protected.
EVIDENCE_MODE_PRODUCTION = "production"
EVIDENCE_MODE_LATER_ASOF = "production_later_asof"


@dataclass(frozen=True)
class FitnessVersionSpec:
    name: str
    description: str
    weights: FitnessWeights
    evidence_mode: str
    return_transform: Callable[[float], float] | None = None


def _v1_weights() -> FitnessWeights:
    """Hardcoded to today's production values (fitness_engine.FitnessWeights defaults /
    config.py's fitness_w_* settings as of this writing) - deliberately NOT read from
    Settings at call time, so "v1" can never silently drift if FITNESS_W_* env vars change
    later. tests/test_fitness_versions.py asserts this still equals
    FitnessWeights.from_settings() today; if that test ever fails, production config has
    moved and v1 needs a conscious decision, not a silent one."""
    return FitnessWeights(
        return_weight=1.0, risk_weight=1.0, consistency_weight=1.0, robustness_weight=1.0,
        oos_weight=1.5, drawdown_penalty_weight=2.0, instability_penalty_weight=1.0,
        correlation_penalty_weight=0.3, expectancy_weight=0.5, regime_weight=1.0,
        adversarial_weight=1.0, inactivity_penalty_weight=0.25, death_penalty_weight=1.0,
    )


def _signed_sqrt_tanh(net_return_pct: float) -> float:
    """A smooth alternative to the hard clip(-1, 1): tanh never fully flattens two large but
    different returns to an identical score the way clip(x, -1, 1) does (e.g. tanh(1.0)=0.762,
    tanh(3.0)=0.995 - still distinguishable; clip(1.0)=clip(3.0)=1.0 exactly). Bounded to (-1, 1)
    same as the production term it replaces."""
    return math.tanh(net_return_pct)


FITNESS_VERSIONS: dict[str, FitnessVersionSpec] = {
    "v1": FitnessVersionSpec(
        name="v1",
        description="Frozen production formula AND production timing: evaluated only at the as_of "
                     "production actually used historically, OOS-window trades excluded exactly as "
                     "compute_and_persist_agent_fitness does. The baseline everything else is measured against.",
        weights=_v1_weights(),
        evidence_mode=EVIDENCE_MODE_PRODUCTION,
    ),
    "v1_timing_fix": FitnessVersionSpec(
        name="v1_timing_fix",
        description="Identical weights and identical OOS-window protection to v1 - the ONLY variable "
                     "that changes is as_of itself, evaluated later so more non-OOS trades have had time "
                     "to close. Never removes or bypasses the OOS exclusion.",
        weights=_v1_weights(),
        evidence_mode=EVIDENCE_MODE_LATER_ASOF,
    ),
    "v2": FitnessVersionSpec(
        name="v2",
        description="v1 + later as_of + modestly reduced OOS dominance (oos_weight 1.5 -> 0.8). "
                     "Everything else unchanged, OOS-window protection intact.",
        weights=replace(_v1_weights(), oos_weight=0.8),
        evidence_mode=EVIDENCE_MODE_LATER_ASOF,
    ),
    "v3": FitnessVersionSpec(
        name="v3",
        description="v1 + later as_of + increased realized-return influence with a controlled "
                     "drawdown penalty (return_weight 1.0 -> 2.0, expectancy_weight 0.5 -> 1.0, "
                     "drawdown_penalty_weight 2.0 -> 1.5). OOS-window protection intact.",
        weights=replace(_v1_weights(), return_weight=2.0, expectancy_weight=1.0, drawdown_penalty_weight=1.5),
        evidence_mode=EVIDENCE_MODE_LATER_ASOF,
    ),
    "v4": FitnessVersionSpec(
        name="v4",
        description="v1 + later as_of + nonlinear (tanh) return transform instead of the hard "
                     "clip(-1,1), with controlled OOS influence (oos_weight 1.5 -> 1.0). Tests directly "
                     "whether the clipping mechanism (confirmed theoretical-only on current data) would "
                     "matter once returns grow. OOS-window protection intact.",
        weights=replace(_v1_weights(), oos_weight=1.0),
        evidence_mode=EVIDENCE_MODE_LATER_ASOF,
        return_transform=_signed_sqrt_tanh,
    ),
}
