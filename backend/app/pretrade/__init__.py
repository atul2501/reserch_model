"""Pre-trade decision architecture — ISOLATED PROTOTYPE (research/shadow only).

Nothing in the live trading path (app.worker, app.agents.decision_loop, app.execution) imports this package; a
test enforces that. It provides the building blocks for an execution path in which every expensive / slow piece of
reasoning (LLM council, models) happens BEFORE the entry opportunity, and the moment of execution only runs cheap,
deterministic checks:

    PreTradeDecision  (decision.py)  - an immutable, versioned record of what was decided, from what information,
                                       at what time, against which signal bar and reference price.
    DecisionCache     (cache.py)     - holds at most one live decision per agent and invalidates it on any material
                                       change; it can never hand out an expired or mismatched decision.
    ExecutionGate     (gate.py)      - the ONLY thing that can say "execute": freshness, signal-bar, information-
                                       cutoff, price-drift, spread, cost, risk, position and conflict checks.
    CouncilView       (council_view.py) - a non-blocking, time-stamped cache of the latest LLM council output.
    LatencyTrace      (latency.py)   - wall-clock stage timestamps and derived latencies.

See research/pretrade_decision_architecture/PRETRADE_ARCHITECTURE_REPORT.md.
"""
from app.pretrade.cache import DecisionCache, InvalidationReason
from app.pretrade.council_view import CouncilSnapshot, CouncilView
from app.pretrade.decision import PreTradeDecision, new_decision
from app.pretrade.gate import ExecutionGate, GateConfig, GateResult, MarketSnapshot
from app.pretrade.latency import LatencyTrace

__all__ = [
    "CouncilSnapshot", "CouncilView", "DecisionCache", "ExecutionGate", "GateConfig", "GateResult",
    "InvalidationReason", "LatencyTrace", "MarketSnapshot", "PreTradeDecision", "new_decision",
]
