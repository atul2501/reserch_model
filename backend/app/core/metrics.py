"""Tiny dependency-free metrics registry (counters, summaries) with Prometheus text exposition (spec phase 37).

In-process: the worker and API each expose their own registry; the worker also publishes its rendered text through the
`SystemStatus` table so the API can report it across processes, and DB-derived gauges (population equity, agent counts,
freshness) are computed at scrape time in `app/api/routes/status.py` - which is why there is no in-process gauge API.

Output follows the exposition format: one `# TYPE` line per metric family, label values escaped, and label cardinality
capped per metric (unbounded labels such as free-text rejection reasons would otherwise grow without limit).
"""
from __future__ import annotations

import threading
from collections import defaultdict

# A metric family may carry at most this many distinct label combinations; further ones fold into `other`.
MAX_SERIES_PER_METRIC = 100

_lock = threading.Lock()
_counters: dict[tuple[str, tuple], float] = defaultdict(float)
_summaries: dict[tuple[str, tuple], list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])  # count, sum, max
_series_per_metric: dict[str, set[tuple]] = defaultdict(set)
OVERFLOW = (("overflow", "other"),)


def _key(name: str, labels: dict | None) -> tuple[str, tuple]:
    key = tuple(sorted((k, str(v)) for k, v in (labels or {}).items()))
    seen = _series_per_metric[name]
    if key not in seen:
        if len(seen) >= MAX_SERIES_PER_METRIC:
            return name, OVERFLOW
        seen.add(key)
    return name, key


def inc(name: str, value: float = 1.0, **labels) -> None:
    with _lock:
        _counters[_key(name, labels)] += value


def observe(name: str, value: float, **labels) -> None:
    with _lock:
        s = _summaries[_key(name, labels)]
        s[0] += 1
        s[1] += value
        s[2] = max(s[2], value)


def counter_value(name: str, **labels) -> float:
    with _lock:
        return _counters.get((name, tuple(sorted((k, str(v)) for k, v in labels.items()))), 0.0)


def reset() -> None:
    with _lock:
        _counters.clear()
        _summaries.clear()
        _series_per_metric.clear()


def record_db_error(operation: str) -> None:
    """One place to count database failures (connection loss, deadlock, constraint violation ...)."""
    inc("db_errors", operation=operation)


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _fmt(name: str, labels: tuple, suffix: str = "") -> str:
    if not labels:
        return f"{name}{suffix}"
    inner = ",".join(f'{k}="{_escape(str(v))}"' for k, v in labels)
    return f"{name}{suffix}{{{inner}}}"


def render_prometheus() -> str:
    lines: list[str] = []
    with _lock:
        by_name: dict[str, list] = defaultdict(list)
        for (name, labels), v in sorted(_counters.items()):
            by_name[name].append((labels, v))
        for name, series in by_name.items():
            lines.append(f"# TYPE {name}_total counter")
            lines.extend(f"{_fmt(name, labels, '_total')} {v}" for labels, v in series)
        sums: dict[str, list] = defaultdict(list)
        for (name, labels), stats in sorted(_summaries.items()):
            sums[name].append((labels, stats))
        for name, series in sums.items():
            lines.append(f"# TYPE {name} summary")
            for labels, (count, total, mx) in series:
                lines.append(f"{_fmt(name, labels, '_count')} {count}")
                lines.append(f"{_fmt(name, labels, '_sum')} {total}")
                lines.append(f"{_fmt(name, labels, '_max')} {mx}")
    return "\n".join(lines) + "\n"
