"""Durable worker lease: only one active decision worker (spec phase 21)."""
from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import get_settings
from app.worker.lease import LeaseKeeper, release, try_acquire


async def test_second_worker_cannot_acquire_a_live_lease(db_session):
    a = await try_acquire(db_session, "worker-A", ttl_seconds=60, now=1000.0)
    b = await try_acquire(db_session, "worker-B", ttl_seconds=60, now=1010.0)
    assert a.acquired and a.epoch == 1
    assert not b.acquired and b.owner_id == "worker-A"


async def test_owner_can_renew_without_epoch_change(db_session):
    a1 = await try_acquire(db_session, "worker-A", 60, now=1000.0)
    a2 = await try_acquire(db_session, "worker-A", 60, now=1030.0)
    assert a1.acquired and a2.acquired and a1.epoch == a2.epoch == 1


async def test_expired_lease_is_taken_over_with_a_new_fencing_epoch(db_session):
    await try_acquire(db_session, "worker-A", 60, now=1000.0)
    b = await try_acquire(db_session, "worker-B", 60, now=1061.0)
    assert b.acquired and b.epoch == 2
    # the superseded worker can no longer renew
    a = await try_acquire(db_session, "worker-A", 60, now=1062.0)
    assert not a.acquired and a.owner_id == "worker-B"


async def test_release_lets_another_worker_start_immediately(db_session):
    await try_acquire(db_session, "worker-A", 60, now=1000.0)
    await release(db_session, "worker-A")
    b = await try_acquire(db_session, "worker-B", 60, now=1001.0)
    assert b.acquired


async def test_concurrent_acquire_race_has_exactly_one_winner():
    # Two independent sessions (as two processes would have) racing for the same row.
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.core.database import Base
    import app.models  # noqa: F401

    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def attempt(owner):
        async with factory() as s:
            return await try_acquire(s, owner, 60)

    results = await asyncio.gather(*(attempt(f"w{i}") for i in range(6)))
    assert sum(r.acquired for r in results) == 1

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def test_keeper_refuses_when_lease_is_held_and_heartbeat_detects_takeover(db_session):
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.core.database import Base
    import app.models  # noqa: F401

    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    k1 = LeaseKeeper(factory, owner_id="k1", ttl_seconds=0.2, heartbeat_seconds=0.05)
    assert await k1.acquire()
    k2 = LeaseKeeper(factory, owner_id="k2", ttl_seconds=60, heartbeat_seconds=10)
    assert not await k2.acquire()  # "worker already active -> do not trade"

    # k1 stalls (stop heartbeating) past its TTL; k2 takes over; k1's next renewal must see it lost.
    k1._task.cancel()
    await asyncio.sleep(0.3)
    assert await k2.acquire()
    k1._task = asyncio.create_task(k1._beat())
    await asyncio.wait_for(k1.lost.wait(), timeout=2)
    assert k1.is_lost

    await k1.close()
    await k2.close()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
