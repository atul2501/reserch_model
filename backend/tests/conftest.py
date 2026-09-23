from __future__ import annotations

import os

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./data/test_trading_lab.db")
os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434")
os.environ.setdefault("OLLAMA_MODEL", "test-model")

from app.core.database import Base  # noqa: E402
import app.models  # noqa: E402,F401


@pytest_asyncio.fixture
async def db_engine():
    """The async engine behind `db_session` (tests that need extra independent sessions use it)."""
    from app.core.config import get_settings

    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    if settings.database_url.startswith("sqlite"):
        # Enforce foreign keys exactly like PostgreSQL does, so fixtures that
        # reference non-existent rows fail on SQLite too (not only on PG).
        from sqlalchemy import event

        @event.listens_for(engine.sync_engine, "connect")
        def _fk_on(dbapi_connection, _):
            cur = dbapi_connection.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    session_factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
