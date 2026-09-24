"""Deterministic, auditable integration of the AI council into an agent's
decision (spec phase 12).

    market features -> AI council -> shared market context -> agent DNA -> signal

The council is SHARED CONTEXT, not an oracle: an agent's own strategy still
decides whether a setup exists and (unless vetoed) which way to trade. The
council can only (a) veto a high-confidence opposed entry, (b) scale size,
(c) block entries entirely when it is INCOMPLETE. It can never bypass the
Risk Engine — the modified notional is still passed through `check_trade`.

A CouncilContext is bound to the candle it was produced for; `for_candle`
refuses to hand a result to any other candle (no stale reuse, ever).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.config import get_settings
from app.models.enums import Bias

NOT_RUN = "NOT_RUN"
COMPLETE = "COMPLETE"
INCOMPLETE = "INCOMPLETE"


@dataclass(frozen=True)
class CouncilContext:
    status: str = NOT_RUN
    bias: Bias | None = None
    confidence: float | None = None
    trade_allowed: bool = True
    candle_open_time: int | None = None
    decision_id: object | None = None
    # Explicit per-cycle requirement. NOT_RUN only means "council approved" when it was NOT required;
    # a required council that did not run (or ran for another candle) blocks new entries.
    required: bool = False

    def for_candle(self, candle_open_time: int) -> "CouncilContext":
        """The context to use for `candle_open_time`. A result produced for a different candle is
        NEVER applied: it is replaced by a fail-closed INCOMPLETE (no new entries), because a
        stale/misbound council decision is a council failure, not "no council"."""
        if self.candle_open_time is not None and self.candle_open_time != candle_open_time:
            return CouncilContext(status=INCOMPLETE, trade_allowed=False, required=True)
        return self


@dataclass(frozen=True)
class CombinedDecision:
    agent_signal: Bias
    council_bias: Bias | None
    council_confidence: float | None
    council_status: str
    final_signal: Bias
    size_modifier: float
    reason: str

    def audit(self) -> dict:
        return {
            "agent_signal": self.agent_signal.value,
            "council_bias": self.council_bias.value if self.council_bias else None,
            "council_confidence": self.council_confidence,
            "council_status": self.council_status,
            "final_signal": self.final_signal.value,
            "size_modifier": self.size_modifier,
            "reason": self.reason,
        }


def combine(agent_signal: Bias, council: CouncilContext | None) -> CombinedDecision:
    s = get_settings()
    c = council or CouncilContext()

    def out(final: Bias, mod: float, reason: str) -> CombinedDecision:
        return CombinedDecision(agent_signal, c.bias, c.confidence, c.status, final, mod, reason)

    if agent_signal == Bias.NEUTRAL:
        return out(Bias.NEUTRAL, 1.0, "no_agent_signal")
    if c.status == INCOMPLETE or not c.trade_allowed:
        return out(Bias.NEUTRAL, 0.0, "council_incomplete_no_new_trades")
    if c.status == NOT_RUN and c.required:
        return out(Bias.NEUTRAL, 0.0, "council_required_but_not_run")
    if c.status == NOT_RUN or c.bias is None:
        return out(agent_signal, 1.0, "council_not_required")

    conf = max(0.0, min(1.0, c.confidence or 0.0))
    if c.bias == Bias.NEUTRAL:
        return out(agent_signal, s.council_neutral_size_modifier, "council_neutral")
    if c.bias == agent_signal:
        return out(agent_signal, 1.0 + s.council_aligned_size_bonus * conf, "council_aligned")
    if conf >= s.council_veto_confidence:
        return out(Bias.NEUTRAL, 0.0, "council_directional_conflict_veto")
    return out(agent_signal, max(0.0, 1.0 - s.council_opposed_size_penalty * conf), "council_opposed_reduced")
