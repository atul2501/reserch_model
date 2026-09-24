"""SQLite write-lock behaviour on a real WAL file shared by two connections (worker cycle vs WS ingestor/heartbeat).

A deferred BEGIN takes a read snapshot at the first SELECT; a commit by another connection before this
transaction's first write makes the upgrade fail instantly ("database is locked", busy_timeout NOT honoured).
BEGIN IMMEDIATE (worker/research processes) takes the lock up front so writers queue instead."""
import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core import database

pytestmark = pytest.mark.skipif(not database._is_sqlite, reason="SQLite-specific locking behaviour")


@pytest.fixture
async def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'lock.db'}")
    database.configure_sqlite_engine(engine.sync_engine, wal=True)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)"))
    yield async_sessionmaker(bind=engine, expire_on_commit=False)
    await engine.dispose()


async def test_deferred_begin_fails_instantly_on_stale_snapshot(factory):
    """Documents the failure mode seen on the worker (API keeps this default)."""
    async with factory() as a, factory() as b:
        await a.execute(text("SELECT count(*) FROM t"))            # A: read snapshot
        await b.execute(text("INSERT INTO t (v) VALUES ('ws')"))   # B: commits a write meanwhile
        await b.commit()
        with pytest.raises(OperationalError, match="database is locked"):
            await a.execute(text("INSERT INTO t (v) VALUES ('cycle')"))


async def test_immediate_begin_makes_concurrent_writers_queue(factory, monkeypatch):
    monkeypatch.setattr(database, "_begin_statement", "BEGIN IMMEDIATE")

    async def cycle():
        async with factory() as a:
            await a.execute(text("SELECT count(*) FROM t"))        # takes the write lock at BEGIN
            await asyncio.sleep(0.3)
            await a.execute(text("INSERT INTO t (v) VALUES ('cycle')"))
            await a.commit()

    async def ws():
        await asyncio.sleep(0.05)                                   # starts while the cycle holds the lock
        async with factory() as b:
            await b.execute(text("INSERT INTO t (v) VALUES ('ws')"))
            await b.commit()

    await asyncio.gather(cycle(), ws())
    async with factory() as s:
        rows = (await s.execute(text("SELECT v FROM t ORDER BY id"))).scalars().all()
    assert sorted(rows) == ["cycle", "ws"]


async def test_immediate_mode_keeps_savepoint_rollback_isolated(factory, monkeypatch):
    """Regression guard for why _on_begin exists: rolling back a per-agent SAVEPOINT must not commit the outer txn."""
    monkeypatch.setattr(database, "_begin_statement", "BEGIN IMMEDIATE")
    async with factory() as a:
        await a.execute(text("INSERT INTO t (v) VALUES ('kept')"))
        with pytest.raises(RuntimeError):
            async with a.begin_nested():
                await a.execute(text("INSERT INTO t (v) VALUES ('rolled_back')"))
                raise RuntimeError("agent failed")
        await a.rollback()                                          # outer txn never committed
    async with factory() as s:
        assert (await s.execute(text("SELECT count(*) FROM t"))).scalar_one() == 0


def test_use_immediate_transactions_is_sqlite_only(monkeypatch):
    monkeypatch.setattr(database, "_begin_statement", "BEGIN")
    monkeypatch.setattr(database, "_is_sqlite", False)
    database.use_immediate_transactions()
    assert database._begin_statement == "BEGIN"
    monkeypatch.setattr(database, "_is_sqlite", True)
    database.use_immediate_transactions()
    assert database._begin_statement == "BEGIN IMMEDIATE"
