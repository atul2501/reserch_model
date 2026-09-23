"""Experiment registry (spec phase 23): every research run is a reproducible,
immutable-by-convention record — dataset fingerprint, periods, strategy,
parameters, code version, schema version, seed."""
from __future__ import annotations

import os
import subprocess
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.research import Experiment, ResearchEpoch

_BACKEND = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def code_version() -> str:
    """Git commit (short) of the running code; `CODE_VERSION` env overrides
    (containers without a .git directory); else 'unknown'."""
    env = os.environ.get("CODE_VERSION")
    if env:
        return env[:64]
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"], cwd=_BACKEND, capture_output=True, text=True, timeout=5
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"], cwd=_BACKEND, capture_output=True, text=True, timeout=5
        ).stdout.strip()
        if sha:
            return f"{sha}{'+dirty' if dirty else ''}"
    except Exception:
        pass
    return "unknown"


@lru_cache(maxsize=1)
def schema_version() -> str:
    """Alembic head revision shipped with this code."""
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config(str(_BACKEND / "alembic.ini"))
        cfg.set_main_option("script_location", str(_BACKEND / "alembic"))
        return ScriptDirectory.from_config(cfg).get_current_head() or "unknown"
    except Exception:
        return "unknown"


def new_experiment_id(kind: str) -> str:
    return f"EXP-{kind[:4].upper()}-{datetime.now(timezone.utc):%Y%m%d%H%M%S}-{uuid.uuid4().hex[:6]}"


async def register_experiment(
    db: AsyncSession,
    *,
    kind: str,
    seed: int,
    parameters: dict,
    epoch: ResearchEpoch | None = None,
    strategy_version_id: uuid.UUID | None = None,
    generation: int | None = None,
    status: str = "RUNNING",
) -> Experiment:
    exp = Experiment(
        experiment_id=new_experiment_id(kind),
        kind=kind,
        status=status,
        epoch_id=epoch.epoch_id if epoch else None,
        dataset_fingerprint=epoch.dataset_fingerprint if epoch else None,
        train_period={"start_ms": epoch.start_ms, "end_ms": epoch.train_end_ms} if epoch else {},
        validation_period={"start_ms": epoch.train_end_ms, "end_ms": epoch.validation_end_ms} if epoch else {},
        oos_period={"start_ms": epoch.validation_end_ms, "end_ms": epoch.end_ms} if epoch else {},
        strategy_version_id=strategy_version_id,
        generation=generation,
        parameters=parameters,
        code_version=code_version(),
        schema_version=schema_version(),
        random_seed=seed,
    )
    db.add(exp)
    await db.flush()
    return exp


async def finish_experiment(db: AsyncSession, exp: Experiment, *, status: str, result: dict) -> None:
    exp.status = status
    exp.result = result
    exp.finished_at = datetime.now(timezone.utc)
    await db.flush()
