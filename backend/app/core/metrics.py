"""Tiny dependency-free metrics registry (counters, gauges, summaries) with
Prometheus text exposition (spec phase 37). In-process: the worker and API
each expose their own registry; the worker also persists key gauges to the DB
(worker_cycles / system_flags) so the API can report them across processes."""
from __future__ import annotations

import threading
from collections import defaultdict

_lock = threading.Lock()
_counters: dict[tuple[str, tuple], float] = defaultdict(float)
_gauges: dict[tuple[str, tuple], float] = {}
_summaries: dict[tuple[str, tuple], list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])  # count, sum, max


def _key(name: str, labels: dict | None) -> tuple[str, tuple]:
    return name, tuple(sorted((labels or {}).items()))


def inc(name: str, value: float = 1.0, **labels) -> None:
    with _lock:
        _counters[_key(name, labels)] += value


def set_gauge(name: str, value: float, **labels) -> None:
    with _lock:
        _gauges[_key(name, labels)] = float(value)


def observe(name: str, value: float, **labels) -> None:
    with _lock:
        s = _summaries[_key(name, labels)]
        s[0] += 1
        s[1] += value
        s[2] = max(s[2], value)


def counter_value(name: str, **labels) -> float:
    with _lock:
        return _counters.get(_key(name, labels), 0.0)


def gauge_value(name: str, **labels) -> float | None:
    with _lock:
        return _gauges.get(_key(name, labels))


def reset() -> None:
    with _lock:
        _counters.clear()
        _gauges.clear()
        _summaries.clear()


def _fmt(name: str, labels: tuple, suffix: str = "") -> str:
    if not labels:
        return f"{name}{suffix}"
    inner = ",".join(f'{k}="{str(v)}"' for k, v in labels)
    return f"{name}{suffix}{{{inner}}}"


def render_prometheus() -> str:
    lines: list[str] = []
    with _lock:
        for (name, labels), v in sorted(_counters.items()):
            lines.append(f"{_fmt(name, labels, '_total')} {v}")
        for (name, labels), v in sorted(_gauges.items()):
            lines.append(f"{_fmt(name, labels)} {v}")
        for (name, labels), (count, total, mx) in sorted(_summaries.items()):
            lines.append(f"{_fmt(name, labels, '_count')} {count}")
            lines.append(f"{_fmt(name, labels, '_sum')} {total}")
            lines.append(f"{_fmt(name, labels, '_max')} {mx}")
    return "\n".join(lines) + "\n"
