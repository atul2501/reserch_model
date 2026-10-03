"""Experiment registry (spec phase 23): every research run is a reproducible,
immutable-by-convention record — dataset fingerprint, periods, strategy,
parameters, code version, schema version, seed."""
from __future__ import annotations

import hashlib
import json
import subprocess
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtesting.engine import ENGINE_VERSION
from app.models.research import Experiment, ResearchEpoch

_BACKEND = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def code_version() -> str:
    """Git commit (short) of the running code; `CODE_VERSION` env overrides
    (containers without a .git directory); else 'unknown'."""
    from app.core.config import get_settings

    configured = get_settings().code_version
    if configured:
        return configured[:64]
    return _git_code_version()


@lru_cache(maxsize=1)
def _git_code_version() -> str:
    """Resolved ONCE per process. It used to spawn two blocking `git` subprocesses on EVERY call - from async
    research code running on the event loop (evaluate_oos_once called it twice per evaluation), stalling lease
    heartbeats for ~0.3 s per evaluation on Windows (process creation is slow there) and a few ms on Linux. The code
    a process is running cannot change while it runs, so the first answer is the right one."""
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


def warm_provenance_cache() -> None:
    """Resolve the per-process provenance constants NOW (git revision: 2 subprocesses; alembic head: parses every
    migration script). Call at process start-up, before the event loop serves lease heartbeats; otherwise the first
    experiment registered pays for both synchronously ON the loop (~0.2-0.4 s on Windows)."""
    _git_code_version()
    schema_version()


def parameter_hash() -> str:
    """Hash of every execution/risk/data parameter that shapes a simulation result. Two experiments with the same
    (code_version, engine_version, parameter_hash, dataset_fingerprint, seed) are the same experiment."""
    from app.core.config import get_settings
    from app.market.feature_engine import FEATURE_WINDOW

    s = get_settings()
    params = {k: getattr(s, k) for k in (
        "paper_fee_rate", "paper_maker_fee_rate", "paper_slippage_bps", "paper_slippage_impact_bps_per_10k",
        "paper_stop_slippage_multiplier", "paper_min_order_notional", "paper_quantity_step", "paper_fill_timing",
        "maintenance_margin_rate", "liquidation_fee_rate", "liquidation_is_fatal", "agent_bankruptcy_equity_fraction",
        "max_leverage", "max_position_size", "max_exposure_multiple", "max_loss_per_trade_fraction", "max_drawdown",
        "max_daily_loss", "agent_starting_balance", "research_train_fraction", "research_validation_fraction",
    )}
    params["feature_window"] = FEATURE_WINDOW
    return hashlib.sha256(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()


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
        engine_version=ENGINE_VERSION,
        parameter_hash=parameter_hash(),
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


async def fail_abandoned_experiments(db: AsyncSession, *, kind: str = "evolution") -> int:
    """Marks every still-RUNNING experiment of `kind` FAILED. Only call it while holding the lease that makes the
    caller the sole runner of that kind: a RUNNING row is then the leftover of a process that died mid-cycle (killed,
    OOM, host restart), which never reaches its own except-branch and would otherwise stay RUNNING forever."""
    stale = (await db.execute(
        select(Experiment).where(Experiment.kind == kind, Experiment.status == "RUNNING")
    )).scalars().all()
    for exp in stale:
        await finish_experiment(db, exp, status="FAILED",
                                result={"error": "abandoned: the research process stopped before the cycle finished"})
    return len(stale)
