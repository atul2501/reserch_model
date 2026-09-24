"""Reproducible randomness for the evolution engine.

Every production path passes an explicit, persisted seed (`Experiment.random_seed`, derived per epoch and
generation). A caller that forgets one must still be REPRODUCIBLE, so the fallback is derived from the inputs
themselves (never from the OS entropy pool): the same DNA in gives the same perturbation out, and different DNAs
still get different streams.
"""
from __future__ import annotations

import random
import zlib


def derived_rng(*parts) -> random.Random:
    blob = "|".join(p.model_dump_json() if hasattr(p, "model_dump_json") else repr(p) for p in parts)
    return random.Random(zlib.crc32(blob.encode()))


def derive_seed(*parts) -> int:
    """A stable 31-bit seed from arbitrary parts, e.g. (research_seed, epoch_id, generation)."""
    return zlib.crc32("|".join(str(p) for p in parts).encode()) & 0x7FFFFFFF
