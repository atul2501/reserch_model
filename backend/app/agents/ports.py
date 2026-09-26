"""Ports the agent-lifecycle domain depends on, so it does not reach directly
into execution internals (Phase 2 dependency-boundary fix, see REFACTOR_PLAN.md
item 2 and REFACTOR_PROGRESS.md).

`lifecycle.py` needs one capability from execution at generation rollover: settle
a position close against a cash balance, recording any bad debt rather than
hiding it. It declares that need here as a `Protocol` instead of importing
`app.execution.accounting` - the caller (an application/orchestration layer that
is already allowed to know about both domain and execution, e.g.
`app.research.pipeline`) supplies the real implementation
(`app.execution.accounting.settle_close`) explicitly. `accounting.Settlement` is
a frozen dataclass with exactly the two fields below, so it satisfies
`SettlementResult` structurally with no change to `app.execution.accounting`.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SettlementResult(Protocol):
    new_balance: float
    bad_debt: float          # >= 0: the part of the loss the account could not cover


@runtime_checkable
class PositionCloseSettler(Protocol):
    """Matches `app.execution.accounting.settle_close` exactly - this describes
    that existing function's contract, not a new one."""

    def __call__(self, balance: float, gross_pnl: float, exit_fee: float) -> SettlementResult: ...
