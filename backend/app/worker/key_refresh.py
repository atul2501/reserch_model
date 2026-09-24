"""Controlled Ollama credential reload for the long-running worker.

`OllamaClient.refresh_keys()` existed but nothing ever called it, so a key that hit 401/403 stayed
disabled until the process was restarted. The worker now refreshes:
  * on SIGHUP (operator edited the env file / rotated a key) -> forced: every key is re-tried;
  * periodically (`ollama_key_refresh_seconds`) -> non-forced: unchanged bad keys stay disabled, so a
    known-bad credential is never hammered, while a replaced/added key becomes usable at once.
"""
from __future__ import annotations

import time

from app.core.logging import get_logger

logger = get_logger(__name__)


class KeyRefresher:
    def __init__(self, client, interval_seconds: float, clock=time.monotonic) -> None:
        self._client = client
        self._interval = interval_seconds
        self._clock = clock
        self._last = clock()
        self._force = False

    def request_forced_refresh(self) -> None:
        """Safe to call from a signal handler."""
        self._force = True

    def tick(self) -> dict | None:
        now = self._clock()
        if not self._force and (self._interval <= 0 or now - self._last < self._interval):
            return None
        force, self._force, self._last = self._force, False, now
        try:
            return self._client.refresh_keys(force=force)
        except Exception:  # noqa: BLE001 - a broken env file must not take the trading loop down
            logger.exception("ollama.key_refresh_failed")
            return None
