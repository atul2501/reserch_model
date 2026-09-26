"""The council's dependency contract on an AI client (Phase 1 dependency-boundary fix,
see REFACTOR_PLAN.md item 3).

`council/service.py` and `council/analysts.py` depend on `AIClientPort`, not on the
concrete `OllamaClient` class — this is a `typing.Protocol` (structural typing), so
`OllamaClient` satisfies it automatically with no change to `OllamaClient` itself, and
tests can pass any object with the right shape (as `tests/test_council_service.py`'s
`ScriptedClient` already did, informally, before this change).

This captures exactly the two methods the council actually calls today: nothing more,
nothing less.
"""
from __future__ import annotations

from typing import Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@runtime_checkable
class AICallStats(Protocol):
    """The subset of OllamaCallStats the council actually reads."""
    request_id: str
    latency_ms: int
    model: str


@runtime_checkable
class AIClientPort(Protocol):
    """Everything the council needs from an AI client. Signature matches
    `OllamaClient.is_available` / `OllamaClient.generate_structured` exactly
    (app/services/ollama_client.py) — this is a description of that existing
    contract, not a new one."""

    def is_available(self) -> bool: ...

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
        temperature: float = 0.2,
        max_retries_override: int | None = None,
        deadline_seconds: float | None = None,
    ) -> tuple[T, AICallStats]: ...
