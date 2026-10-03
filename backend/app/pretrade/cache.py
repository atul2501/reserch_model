"""DecisionCache — at most one live decision per agent; stale or mismatched decisions are never returned."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.pretrade.decision import PreTradeDecision


class InvalidationReason(str, Enum):
    NEW_SIGNAL_BAR = "new_signal_bar"
    SIGNAL_CHANGED = "signal_changed"
    DIRECTION_CHANGED = "direction_changed"
    REGIME_CHANGED = "regime_changed"
    CONDITIONS_GONE = "strategy_conditions_gone"
    PRICE_MOVED = "price_moved_too_far"
    TOO_OLD = "decision_too_old"
    RISK_CHANGED = "risk_conditions_changed"
    POSITION_CHANGED = "position_state_changed"
    CONFLICTING_SIGNAL = "conflicting_signal"
    REPLACED = "replaced_by_newer_decision"
    CONSUMED = "consumed_by_execution"


@dataclass
class _Entry:
    decision: PreTradeDecision
    position_state: str            # e.g. "FLAT" / "LONG" / "SHORT" when the decision was made
    risk_epoch: int                # bumped by the caller whenever risk limits/balances change materially


@dataclass
class DecisionCache:
    max_age_ms: int
    max_drift_bps: float | None = None
    _entries: dict[str, _Entry] = field(default_factory=dict)
    invalidations: list[tuple[str, str, InvalidationReason]] = field(default_factory=list)  # (agent, decision, why)

    def put(self, decision: PreTradeDecision, *, position_state: str, risk_epoch: int) -> None:
        old = self._entries.get(decision.agent_id)
        if old is not None:
            reason = (InvalidationReason.CONFLICTING_SIGNAL if old.decision.direction != decision.direction
                      else InvalidationReason.REPLACED)
            self._drop(decision.agent_id, reason)
        self._entries[decision.agent_id] = _Entry(decision, position_state, risk_epoch)

    def _drop(self, agent_id: str, reason: InvalidationReason) -> None:
        e = self._entries.pop(agent_id, None)
        if e is not None:
            self.invalidations.append((agent_id, e.decision.decision_id, reason))

    def invalidate(self, agent_id: str, reason: InvalidationReason) -> None:
        self._drop(agent_id, reason)

    def get(
        self, agent_id: str, *, now_ms: int, current_signal_bar_ms: int, position_state: str, risk_epoch: int,
        current_price: float | None = None, current_regime: str | None = None,
        current_direction: str | None = None, conditions_hold: bool = True,
    ) -> PreTradeDecision | None:
        """Returns the cached decision only if it is still valid for THIS moment; otherwise invalidates it (with a
        recorded reason) and returns None. A caller can therefore never execute a stale decision by accident."""
        e = self._entries.get(agent_id)
        if e is None:
            return None
        d = e.decision
        checks = [
            (d.signal_bar_open_time_ms != current_signal_bar_ms, InvalidationReason.NEW_SIGNAL_BAR),
            (d.age_ms(now_ms) > self.max_age_ms, InvalidationReason.TOO_OLD),
            (e.position_state != position_state, InvalidationReason.POSITION_CHANGED),
            (e.risk_epoch != risk_epoch, InvalidationReason.RISK_CHANGED),
            (current_regime is not None and d.regime is not None and current_regime != d.regime, InvalidationReason.REGIME_CHANGED),
            (current_direction is not None and current_direction != d.direction, InvalidationReason.DIRECTION_CHANGED),
            (not conditions_hold, InvalidationReason.CONDITIONS_GONE),
            (self.max_drift_bps is not None and current_price is not None
             and abs(current_price / d.reference_price - 1) * 1e4 > self.max_drift_bps, InvalidationReason.PRICE_MOVED),
        ]
        for failed, reason in checks:
            if failed:
                self._drop(agent_id, reason)
                return None
        return d

    def consume(self, agent_id: str) -> None:
        """A decision is single-use: once executed (or attempted) it leaves the cache."""
        self._drop(agent_id, InvalidationReason.CONSUMED)

    def on_new_bar(self, bar_open_ms: int) -> None:
        for agent_id in [a for a, e in self._entries.items() if e.decision.signal_bar_open_time_ms != bar_open_ms]:
            self._drop(agent_id, InvalidationReason.NEW_SIGNAL_BAR)

    def __len__(self) -> int:
        return len(self._entries)
