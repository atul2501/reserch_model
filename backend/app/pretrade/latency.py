"""LatencyTrace — explicit wall-clock stage timestamps (ms since epoch) and derived latencies."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

STAGES = (
    "market_event_at", "features_started_at", "features_completed_at", "signal_created_at", "llm_started_at",
    "llm_completed_at", "decision_created_at", "execution_validation_at", "order_submitted_at", "exchange_ack_at",
    "fill_at",
)


def now_ms() -> int:
    return time.time_ns() // 1_000_000


@dataclass
class LatencyTrace:
    stamps: dict[str, int] = field(default_factory=dict)

    def mark(self, stage: str, at_ms: int | None = None) -> None:
        if stage not in STAGES:
            raise ValueError(f"unknown stage {stage!r}")
        self.stamps[stage] = now_ms() if at_ms is None else at_ms

    def _d(self, a: str, b: str) -> int | None:
        return self.stamps[b] - self.stamps[a] if a in self.stamps and b in self.stamps else None

    def derived(self) -> dict[str, int | None]:
        return {
            "feature_latency_ms": self._d("features_started_at", "features_completed_at"),
            "strategy_latency_ms": self._d("features_completed_at", "signal_created_at"),
            "llm_latency_ms": self._d("llm_started_at", "llm_completed_at"),
            "decision_latency_ms": self._d("market_event_at", "decision_created_at"),
            "execution_latency_ms": self._d("execution_validation_at", "order_submitted_at"),
            "ack_latency_ms": self._d("order_submitted_at", "exchange_ack_at"),
            "total_signal_to_fill_ms": self._d("market_event_at", "fill_at"),
        }

    def is_monotonic(self) -> bool:
        """Stages present must not go backwards in pipeline order (llm_* are allowed to be absent)."""
        seq = [self.stamps[s] for s in STAGES if s in self.stamps and not s.startswith("llm_")]
        return all(a <= b for a, b in zip(seq, seq[1:]))
