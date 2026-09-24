"""Durable single-worker lease (spec: only one active decision worker).

The acquire/renew step is a single atomic statement pair executed by the
database — `INSERT ... ON CONFLICT DO NOTHING` then a conditional `UPDATE ...
WHERE owner = me OR expires_at < now` — so two processes racing on the same
row can never both win, on SQLite or PostgreSQL. Every ownership change bumps
`epoch` (a fencing token). A background heartbeat renews the lease while a
long cycle runs and flags `lost` if it is ever taken over.
"""
from __future__ import annotations

import asyncio
import os
import socket
import time
import uuid
from dataclasses import dataclass

from sqlalchemy import case, or_, select, update
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import metrics
from app.core.logging import get_logger
from app.models.base import utcnow
from app.models.system import WorkerLease

logger = get_logger(__name__)

DECISION_WORKER = "decision-worker"


class LeaseLost(RuntimeError):
    """This worker no longer holds the lease (superseded, expired, or unable to renew within the TTL).
    Everything it was about to write must be abandoned: it is FENCED OFF."""


def new_owner_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


@dataclass(frozen=True)
class LeaseState:
    acquired: bool
    owner_id: str | None
    epoch: int | None


async def db_now(db: AsyncSession) -> float:
    """The clock lease expiry is judged by. On PostgreSQL that is the DATABASE's clock, so hosts with skewed wall clocks
    cannot disagree about who holds the lease; SQLite is single-host, where the process clock is the same thing."""
    if db.get_bind().dialect.name == "postgresql":
        from sqlalchemy import text

        return float((await db.execute(text("SELECT extract(epoch FROM clock_timestamp())"))).scalar_one())
    return time.time()


def _insert_fn(db: AsyncSession):
    return postgresql.insert if db.get_bind().dialect.name == "postgresql" else sqlite.insert


async def try_acquire(
    db: AsyncSession, owner_id: str, ttl_seconds: float, *, name: str = DECISION_WORKER, now: float | None = None
) -> LeaseState:
    """Acquire or renew. Never raises for "held by someone else"."""
    now = await db_now(db) if now is None else now
    stamp = utcnow()
    ins = _insert_fn(db)(WorkerLease).values(
        name=name, owner_id=owner_id, expires_at=now + ttl_seconds, epoch=1, heartbeat_at=now,
        created_at=stamp, updated_at=stamp,
    ).on_conflict_do_nothing(index_elements=["name"])
    result = await db.execute(ins)
    if result.rowcount == 1:
        await db.commit()
        return LeaseState(True, owner_id, 1)

    upd = (
        update(WorkerLease)
        .where(WorkerLease.name == name, or_(WorkerLease.owner_id == owner_id, WorkerLease.expires_at < now))
        .values(
            owner_id=owner_id,
            expires_at=now + ttl_seconds,
            heartbeat_at=now,
            epoch=case((WorkerLease.owner_id == owner_id, WorkerLease.epoch), else_=WorkerLease.epoch + 1),
            updated_at=stamp,
        )
        .execution_options(synchronize_session=False)
    )
    result = await db.execute(upd)
    await db.commit()
    row = (await db.execute(select(WorkerLease).where(WorkerLease.name == name))).scalar_one()
    await db.refresh(row)
    if result.rowcount == 1:
        return LeaseState(True, owner_id, row.epoch)
    return LeaseState(False, row.owner_id, row.epoch)


async def release(db: AsyncSession, owner_id: str, *, name: str = DECISION_WORKER) -> None:
    await db.execute(
        update(WorkerLease)
        .where(WorkerLease.name == name, WorkerLease.owner_id == owner_id)
        .values(expires_at=0.0)
        .execution_options(synchronize_session=False)
    )
    await db.commit()


class LeaseKeeper:
    """Holds the lease for the worker's lifetime with a renewing heartbeat."""

    def __init__(self, session_factory, *, owner_id: str | None = None, ttl_seconds: float = 90, heartbeat_seconds: float = 30,
                 name: str = DECISION_WORKER) -> None:
        self._session_factory = session_factory
        self.owner_id = owner_id or new_owner_id()
        self._ttl = ttl_seconds
        self._heartbeat = heartbeat_seconds
        self._name = name
        self._task: asyncio.Task | None = None
        self.epoch: int | None = None
        self.lost = asyncio.Event()
        # Local (DB-independent) self-fence: monotonic time of the last renewal REQUEST that succeeded. If the
        # database is unreachable for longer than the TTL, another worker may legitimately have taken over,
        # so this worker must stop on its own without being able to ask the database.
        self._last_renewed = time.monotonic()

    async def acquire(self) -> bool:
        requested = time.monotonic()
        async with self._session_factory() as db:
            state = await try_acquire(db, self.owner_id, self._ttl, name=self._name)
        if not state.acquired:
            logger.error("worker.lease_held_by_other", owner_id=state.owner_id)
            return False
        self.epoch = state.epoch
        self._last_renewed = requested
        self.lost.clear()
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._beat(), name="lease-heartbeat")
        return True

    async def _beat(self) -> None:
        while True:
            await asyncio.sleep(self._heartbeat)
            requested = time.monotonic()
            try:
                async with self._session_factory() as db:
                    state = await try_acquire(db, self.owner_id, self._ttl, name=self._name)
                if not state.acquired or state.epoch != self.epoch:
                    logger.critical("worker.lease_lost", new_owner=state.owner_id)
                    metrics.inc("lease_lost", reason="superseded")
                    self.lost.set()
                    return
                self._last_renewed = requested
            except Exception as exc:  # transient DB error: keep trying until the TTL truly lapses
                logger.warning("worker.lease_heartbeat_failed", error=str(exc))
                metrics.inc("db_errors", operation="lease_heartbeat")
                if time.monotonic() - self._last_renewed > self._ttl:
                    # We can no longer prove we hold the lease and someone else may have it: stop trading.
                    logger.critical("worker.lease_expired_locally_self_fencing")
                    metrics.inc("lease_lost", reason="local_ttl_expired")
                    self.lost.set()
                    return

    @property
    def is_lost(self) -> bool:
        return self.lost.is_set()

    # -- fencing -------------------------------------------------------------------------------- #
    def check_local(self) -> None:
        """Cheap, no I/O: raise LeaseLost if the lease was lost or could not be renewed within the TTL."""
        if not self.lost.is_set() and self.epoch is not None and time.monotonic() - self._last_renewed <= self._ttl:
            return
        if not self.lost.is_set():
            metrics.inc("lease_lost", reason="not_held_or_ttl_lapsed")
            self.lost.set()
        raise LeaseLost(f"worker {self.owner_id} does not hold the {self._name} lease")

    async def check_db(self, db: AsyncSession, *, lock: bool = False) -> None:
        """Verify, INSIDE the caller's transaction, that we still own the lease at our fencing epoch and that it
        has not expired. With `lock=True` on PostgreSQL the row is share-locked until the transaction ends, so a
        takeover cannot slip in between this check and the commit that follows it."""
        self.check_local()
        stmt = select(WorkerLease.owner_id, WorkerLease.epoch, WorkerLease.expires_at).where(WorkerLease.name == self._name)
        if lock and db.get_bind().dialect.name == "postgresql":
            stmt = stmt.with_for_update(read=True)
        row = (await db.execute(stmt)).one_or_none()
        if row is None or row.owner_id != self.owner_id or row.epoch != self.epoch or row.expires_at <= await db_now(db):
            metrics.inc("lease_lost", reason="fenced_at_commit")
            self.lost.set()
            await db.rollback()
            raise LeaseLost(
                f"fenced: lease is now owner={getattr(row, 'owner_id', None)} epoch={getattr(row, 'epoch', None)} "
                f"(this worker: {self.owner_id} epoch={self.epoch})"
            )

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        try:
            async with self._session_factory() as db:
                await release(db, self.owner_id, name=self._name)
        except Exception as exc:
            logger.warning("worker.lease_release_failed", error=str(exc))
