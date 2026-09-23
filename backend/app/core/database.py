"""Async SQLAlchemy engine/session management."""
from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()
_is_sqlite = _settings.database_url.startswith("sqlite")

_engine_kwargs: dict = {"pool_pre_ping": True}
if not _is_sqlite:
    _engine_kwargs.update(
        pool_size=_settings.database_pool_size,
        max_overflow=_settings.database_max_overflow,
        pool_timeout=_settings.database_pool_timeout_seconds,
        pool_recycle=_settings.database_pool_recycle_seconds,  # survive server-side idle disconnects
    )
    if _settings.database_url.startswith("postgresql+asyncpg"):
        # A runaway query must not hold a pooled connection (and locks) forever.
        _engine_kwargs["connect_args"] = {
            "server_settings": {"statement_timeout": str(_settings.database_statement_timeout_ms)}
        }

engine = create_async_engine(_settings.database_url, **_engine_kwargs)

if _is_sqlite:
    # SQLite disables foreign-key enforcement by default; the schema relies
    # on FKs, so turn it on for every new DBAPI connection.
    @event.listens_for(engine.sync_engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        # API and worker are separate processes sharing this file: WAL lets
        # readers proceed during a write and busy_timeout turns transient
        # lock contention into a short wait instead of "database is locked".
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a request-scoped session."""
    async with AsyncSessionLocal() as session:
        yield session


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for a transactional unit of work outside a request.

    Commits on success, rolls back on any exception — used by background
    services (population manager, evolution engine, market ingestion) that
    are not driven by a FastAPI request.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
