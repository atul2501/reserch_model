"""Data split utilities (spec section 23).

Enforces strict chronological separation between TRAIN / VALIDATION / FINAL
TEST. The final test slice is meant to be touched rarely — callers should
not run repeated optimization loops against it (this module can't enforce
that by itself, but it keeps the slices explicit and named so a research
pipeline can log what it used and when).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class DataSplit:
    train: pd.DataFrame
    validation: pd.DataFrame
    final_test: pd.DataFrame


def chronological_split(
    candles: pd.DataFrame,
    *,
    train_fraction: float = 0.6,
    validation_fraction: float = 0.2,
) -> DataSplit:
    """Splits strictly in time order (never shuffled — this is time series
    data, and shuffling would leak future information into training)."""
    if not 0 < train_fraction < 1 or not 0 < validation_fraction < 1:
        raise ValueError("fractions must be between 0 and 1")
    if train_fraction + validation_fraction >= 1:
        raise ValueError("train_fraction + validation_fraction must leave room for final_test")

    n = len(candles)
    train_end = int(n * train_fraction)
    val_end = train_end + int(n * validation_fraction)

    return DataSplit(
        train=candles.iloc[:train_end].reset_index(drop=True),
        validation=candles.iloc[train_end:val_end].reset_index(drop=True),
        final_test=candles.iloc[val_end:].reset_index(drop=True),
    )
