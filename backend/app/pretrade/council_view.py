"""CouncilView — the LLM council OFF the critical path.

The council is launched as a background task on a confirmed bar; the execution path only ever READS the latest
completed snapshot (an O(1) attribute access) and never awaits it. Each snapshot carries the information cutoff of
the bar it analysed, so its age is explicit and the gate can refuse a stale one.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable


@dataclass(frozen=True)
class CouncilSnapshot:
    bias: str                   # LONG | SHORT | NEUTRAL
    confidence: float
    information_cutoff_ms: int  # close of the bar the council analysed
    completed_at_ms: int        # wall clock when the result became available
    model_version: str | None
    prompt_version: str | None
    status: str                 # COMPLETE | INCOMPLETE


class CouncilView:
    def __init__(self) -> None:
        self._latest: CouncilSnapshot | None = None
        self._task: asyncio.Task | None = None

    def latest(self, *, now_ms: int, max_age_ms: int) -> CouncilSnapshot | None:
        """Non-blocking read. Returns None when there is no COMPLETE snapshot fresh enough for `now_ms`."""
        s = self._latest
        if s is None or s.status != "COMPLETE" or now_ms - s.information_cutoff_ms > max_age_ms:
            return None
        return s

    def publish(self, snap: CouncilSnapshot) -> None:
        """Records a council result produced elsewhere (in shadow mode: the existing path's own council run, so the
        LLM is never called twice). Older-cutoff results never overwrite newer ones."""
        if self._latest is None or snap.information_cutoff_ms >= self._latest.information_cutoff_ms:
            self._latest = snap

    def latest_any(self) -> CouncilSnapshot | None:
        """Most recent snapshot regardless of age/status (for shadow RECORDING only, never for decisions)."""
        return self._latest

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def launch(self, run: Callable[[], Awaitable[CouncilSnapshot]]) -> bool:
        """Starts a council run in the background unless one is already running (never queues up behind a slow LLM).
        Returns False when skipped."""
        if self.running:
            return False

        async def _wrap() -> None:
            try:
                snap = await run()
            except Exception:  # noqa: BLE001 - a failed council simply leaves the previous snapshot to age out
                return
            if self._latest is None or snap.information_cutoff_ms >= self._latest.information_cutoff_ms:
                self._latest = snap

        self._task = asyncio.get_running_loop().create_task(_wrap())
        return True
