"""ExecutionGate — the deterministic authority on whether a decision may be executed NOW.

An LLM/model output is an INPUT to a decision; it can never authorise execution. Every check is pure and cheap
(no I/O), so validation takes microseconds. All failures are reported (not just the first) for shadow analysis.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.pretrade.decision import PreTradeDecision


@dataclass(frozen=True)
class GateConfig:
    max_decision_age_ms: int = 5_000            # research parameter (1/2/5/10/15/30 s tested), NOT a tuned value
    max_entry_drift_bps: float = 10.0           # research parameter (2/5/10/15/20 bps tested)
    max_spread_bps: float | None = None         # None = spread not checked (no book data in the current system)
    require_spread: bool = False                # True = an unknown spread fails closed
    round_trip_cost_bps: float = 13.5           # measured: fees 8.67 + slippage 4.81 (forensic audit)
    cost_margin_bps: float = 0.0
    require_expected_move: bool = False         # True = no expected_move_bps -> reject; False -> flagged, not passed on it
    max_council_age_ms: int | None = None       # None = council not used by the gate at all
    require_council: bool = False


@dataclass(frozen=True)
class MarketSnapshot:
    now_ms: int                                 # wall clock at validation
    current_signal_bar_ms: int                  # the bar the execution opportunity belongs to
    current_price: float                        # best available executable/mark price NOW
    spread_bps: float | None = None
    position_open: bool = False
    pending_order: bool = False
    risk_ok: bool = True                        # result of the existing Risk Engine (never bypassed)
    risk_reasons: tuple[str, ...] = ()
    conflicting_signal: bool = False


@dataclass(frozen=True)
class GateResult:
    allowed: bool
    reasons: tuple[str, ...]                    # every failed check; empty when allowed
    flags: tuple[str, ...]                      # non-blocking observations (e.g. cost_check_unavailable)
    decision_age_ms: int
    price_drift_bps: float                      # signed: + = price moved in the trade's favour since the decision
    validation_us: float = field(default=0.0)


class ExecutionGate:
    def __init__(self, config: GateConfig) -> None:
        self.config = config

    def validate(self, d: PreTradeDecision, m: MarketSnapshot) -> GateResult:
        t0 = time.perf_counter()
        c = self.config
        reasons: list[str] = []
        flags: list[str] = []
        age = d.age_ms(m.now_ms)
        drift = (m.current_price / d.reference_price - 1) * 1e4 * d.sign

        if d.signal_bar_open_time_ms != m.current_signal_bar_ms:
            reasons.append("stale_signal_bar")
        if d.features_as_of_ms > d.information_cutoff_ms:
            reasons.append("features_after_information_cutoff")
        if d.decision_timestamp_ms < d.information_cutoff_ms:
            reasons.append("decision_predates_its_information")       # decided before the bar closed = look-ahead
        if m.now_ms < d.information_cutoff_ms:
            reasons.append("execution_before_information_cutoff")     # would mean acting on an unclosed bar
        if age > c.max_decision_age_ms:
            reasons.append("decision_too_old")
        if abs(drift) > c.max_entry_drift_bps:
            reasons.append("price_moved_too_far")
        if m.spread_bps is None:
            if c.require_spread:
                reasons.append("spread_unknown")
            else:
                flags.append("spread_not_checked")
        elif c.max_spread_bps is not None and m.spread_bps > c.max_spread_bps:
            reasons.append("spread_too_wide")
        if d.expected_move_bps is None:
            if c.require_expected_move:
                reasons.append("expected_move_unavailable")
            else:
                flags.append("cost_check_unavailable")
        elif d.expected_move_bps < c.round_trip_cost_bps + c.cost_margin_bps:
            reasons.append("expected_move_below_cost")
        if not m.risk_ok:
            reasons.append("risk_rejected")
        if m.position_open:
            reasons.append("position_already_open")
        if m.pending_order:
            reasons.append("order_already_pending")
        if m.conflicting_signal:
            reasons.append("conflicting_signal")
        if c.require_council:
            if d.council_cutoff_ms is None:
                reasons.append("council_unavailable")
            elif c.max_council_age_ms is not None and m.now_ms - d.council_cutoff_ms > c.max_council_age_ms:
                reasons.append("council_too_old")
        return GateResult(
            allowed=not reasons, reasons=tuple(reasons), flags=tuple(flags), decision_age_ms=age,
            price_drift_bps=drift, validation_us=(time.perf_counter() - t0) * 1e6,
        )
