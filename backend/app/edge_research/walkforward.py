"""Strict chronological walk-forward windows. No shuffling, no overlap, an embargo between every split.

    |----- TRAIN (expanding) -----| emb |-- VAL --| emb |-- OOS-1 --|
    |----------- TRAIN ----------------------| emb |-- VAL --| emb |-- OOS-2 --|   ...

Rows are assigned by DECISION time; a row is only usable in TRAIN/VAL if its OUTCOME (decision + horizon) is known
before the next split starts (purging), so no future information leaks backwards.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

DAY_MS = 86_400_000


@dataclass(frozen=True)
class Window:
    name: str
    train: tuple[int, int]
    val: tuple[int, int]
    oos: tuple[int, int]


def make_windows(t_start: int, t_end: int, *, oos_ms: int, val_ms: int, min_train_ms: int, embargo_ms: int,
                 max_windows: int = 12) -> list[Window]:
    """Consecutive, non-overlapping OOS windows walking forward from the earliest point with enough history."""
    out = []
    oos_start = t_start + min_train_ms + embargo_ms + val_ms + embargo_ms
    i = 1
    while oos_start + oos_ms <= t_end and len(out) < max_windows:
        val_end = oos_start - embargo_ms
        val_start = val_end - val_ms
        train_end = val_start - embargo_ms
        out.append(Window(f"OOS-{i}", (t_start, train_end), (val_start, val_end), (oos_start, oos_start + oos_ms)))
        oos_start += oos_ms
        i += 1
    return out


def split(df: pd.DataFrame, w: Window, *, horizon_ms: int, t_col: str = "t") -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    t = df[t_col].to_numpy()
    known = t + horizon_ms                                    # when the row's label becomes known
    tr = df[(t >= w.train[0]) & (t < w.train[1]) & (known < w.val[0])]
    va = df[(t >= w.val[0]) & (t < w.val[1]) & (known < w.oos[0])]
    oo = df[(t >= w.oos[0]) & (t < w.oos[1])]
    return tr, va, oo


def assert_no_leakage(tr: pd.DataFrame, va: pd.DataFrame, oo: pd.DataFrame, *, horizon_ms: int, t_col: str = "t") -> None:
    if len(tr) and len(va):
        assert (tr[t_col] + horizon_ms).max() < va[t_col].min(), "train labels overlap validation"
    if len(va) and len(oo):
        assert (va[t_col] + horizon_ms).max() < oo[t_col].min(), "validation labels overlap OOS"
    if len(tr) and len(oo):
        assert tr[t_col].max() < oo[t_col].min(), "train overlaps OOS"


def windows_for(df: pd.DataFrame, *, horizon_min: int, t_col: str = "t", oos_days: float = 1.0, val_days: float = 1.0,
                min_train_days: float = 2.0) -> list[Window]:
    if df.empty:
        return []
    emb = max(horizon_min * 60_000, 60 * 60_000)              # at least 1 h embargo
    return make_windows(int(df[t_col].min()), int(df[t_col].max()) + 1, oos_ms=int(oos_days * DAY_MS),
                        val_ms=int(val_days * DAY_MS), min_train_ms=int(min_train_days * DAY_MS), embargo_ms=emb)


def quantile_threshold(scores: np.ndarray, top_frac: float) -> float:
    return float(np.quantile(scores, 1 - top_frac)) if top_frac < 1 else -np.inf
