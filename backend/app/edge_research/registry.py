"""Append-only experiment registry with duplicate / material-equivalence detection.

Storage: one JSON object per line (default research/edge_registry/experiments.jsonl at the repository root, override
with EDGE_REGISTRY_PATH). A plain file on purpose: portable, diffable, reviewable by another person or AI, and it
never touches the trading database.

Equivalence policy (the "do not repeat the last 25 days" rule):
  EXACT     same spec_hash (signal source, universe, features, target, horizon, model, hyperparameters, selection,
            exit, cost model) -> refused, UNLESS the new data window ends >= MIN_NEW_DAYS later than every earlier run
            (genuinely unseen data = a legitimate replication, recorded as such).
  NEEDS_MORE_DATA  an exact match whose earlier runs all ended NEEDS_MORE_DATA may re-run as soon as ANY newer data exists.
  MATERIAL  same signal source + feature set + model family, different horizon/hyperparameters/selection, and every
            earlier equivalent was REJECTED/OOS_FAILED -> refused unless a written justification is supplied AND the data
            is new (as above). Re-tuning knobs of a hypothesis that already failed out of sample is model shopping.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import BACKEND_DIR, get_settings

MIN_NEW_DAYS = 3.0
FAILED_DECISIONS = {"REJECTED", "OOS_FAILED"}
DECISIONS = ("REJECTED", "PROMISING", "NEEDS_MORE_DATA", "OOS_FAILED", "ACCEPTED_FOR_SHADOW")
DAY_MS = 86_400_000


def default_registry_path() -> Path:
    configured = get_settings().edge_registry_path
    return Path(configured) if configured else BACKEND_DIR.parent / "research" / "edge_registry" / "experiments.jsonl"


@dataclass(frozen=True)
class ExperimentSpec:
    hypothesis: str
    signal_source: str                  # e.g. "strategy_signals:traded", "bar:microstructure", "bar:btc_lead"
    features: tuple[str, ...]
    target: str                         # e.g. "signed_fwd_return_net_bps"
    horizon_min: int
    model: str                          # "rule" | "ridge"
    universe: dict = field(default_factory=dict)          # filters (family, side, regime...)
    hyperparameters: dict = field(default_factory=dict)
    selection: str = "validation_top_quantile"            # how the trade threshold is chosen (always on VALIDATION)
    exit: str = "fixed_horizon_bar_close"
    cost_model: str = "measured"

    def canonical(self) -> dict:
        d = asdict(self)
        d.pop("hypothesis")
        d["features"] = sorted(d["features"])
        return json.loads(json.dumps(d, sort_keys=True))

    @property
    def spec_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.canonical(), sort_keys=True).encode()).hexdigest()[:16]

    @property
    def family_hash(self) -> str:
        """Material identity: signal source + features + model family (horizon/knobs/selection excluded)."""
        key = {"signal_source": self.signal_source, "features": sorted(self.features), "model": self.model,
               "universe": self.universe}
        return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:16]


@dataclass
class DuplicateCheck:
    allowed: bool
    level: str                          # "NEW" | "EXACT_REPLICATION" | "EXACT" | "MATERIAL" | "MATERIAL_JUSTIFIED"
    previous: list[dict]
    message: str


class ExperimentRegistry:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else default_registry_path()

    def all(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def append(self, record: dict) -> dict:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if record.get("decision") not in DECISIONS:
            raise ValueError(f"decision must be one of {DECISIONS}")
        with self.path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(record, sort_keys=True, default=str) + "\n")
        return record

    def check(self, spec: ExperimentSpec, *, data_end_ms: int | None, justification: str | None = None) -> DuplicateCheck:
        prior = self.all()
        exact = [r for r in prior if r.get("spec_hash") == spec.spec_hash]
        material = [r for r in prior if r.get("family_hash") == spec.family_hash and r.get("spec_hash") != spec.spec_hash]

        def new_data(rs):
            ends = [r.get("data_end_ms") for r in rs if r.get("data_end_ms") is not None]
            return data_end_ms is not None and (not ends or data_end_ms >= max(ends) + MIN_NEW_DAYS * DAY_MS)

        if exact and all(r.get("decision") == "NEEDS_MORE_DATA" for r in exact):
            ends = [r.get("data_end_ms") or 0 for r in exact]
            if data_end_ms is None or data_end_ms > max(ends):
                return DuplicateCheck(True, "EXACT_MORE_DATA", exact,
                                      "Earlier runs had insufficient evidence (NEEDS_MORE_DATA); re-running on more data is allowed.")
            return DuplicateCheck(False, "EXACT", exact, _already_tested(exact) + " No new data since then.")
        if exact:
            if new_data(exact):
                return DuplicateCheck(True, "EXACT_REPLICATION", exact,
                                      "Same hypothesis on >= %.0f days of NEW data: allowed as an out-of-sample replication." % MIN_NEW_DAYS)
            return DuplicateCheck(False, "EXACT", exact, _already_tested(exact))
        if material and all(r.get("decision") in FAILED_DECISIONS for r in material):
            if justification and new_data(material):
                return DuplicateCheck(True, "MATERIAL_JUSTIFIED", material, f"Re-test of a failed family on new data: {justification}")
            return DuplicateCheck(False, "MATERIAL", material,
                                  _already_tested(material) + " Changing horizon/hyperparameters/threshold of a hypothesis that "
                                  "already failed out of sample is model shopping. Needs NEW data and a written justification.")
        return DuplicateCheck(True, "NEW", material, "No equivalent experiment in the registry.")

    def record(self, spec: ExperimentSpec, *, result: dict, decision: str, status: str, data_start_ms: int | None,
               data_end_ms: int | None, duplicate_level: str, notes: str = "", seed: bool = False) -> dict:
        rec = {
            "experiment_id": f"EDGE-{datetime.now(timezone.utc):%Y%m%d%H%M%S}-{uuid.uuid4().hex[:6]}" if not seed else result.get("experiment_id"),
            "date": datetime.now(timezone.utc).isoformat(), "seed": seed, "hypothesis": spec.hypothesis,
            "spec": spec.canonical(), "spec_hash": spec.spec_hash, "family_hash": spec.family_hash,
            "features": sorted(spec.features), "target": spec.target, "horizon_min": spec.horizon_min, "model": spec.model,
            "hyperparameters": spec.hyperparameters, "data_start_ms": data_start_ms, "data_end_ms": data_end_ms,
            "status": status, "decision": decision, "duplicate_level": duplicate_level, "notes": notes, **result,
        }
        return self.append(rec)


def _already_tested(rs: list[dict]) -> str:
    lines = [f"{r.get('experiment_id')} ({str(r.get('date'))[:10]}): {r.get('status')} / {r.get('decision')} - "
             f"OOS net {r.get('oos_net_expectancy_bps')} bps" for r in rs[-5:]]
    return "This hypothesis has already been tested. Previous result: " + "; ".join(lines) + "."
