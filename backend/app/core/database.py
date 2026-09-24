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

def postgres_connect_args(settings) -> dict:
    """asyncpg session settings: a runaway query, a lock wait or a forgotten open transaction must not hold a pooled
    connection (and its locks) forever."""
    return {
        "server_settings": {
            "statement_timeout": str(settings.database_statement_timeout_ms),
            "lock_timeout": str(settings.database_lock_timeout_ms),
            "idle_in_transaction_session_timeout": str(settings.database_idle_in_transaction_timeout_ms),
            "application_name": "trading-lab",
        }
    }


_engine_kwargs: dict = {"pool_pre_ping": True}
if not _is_sqlite:
    _engine_kwargs.update(
        pool_size=_settings.database_pool_size,
        max_overflow=_settings.database_max_overflow,
        pool_timeout=_settings.database_pool_timeout_seconds,
        pool_recycle=_settings.database_pool_recycle_seconds,  # survive server-side idle disconnects
    )
    if _settings.database_url.startswith("postgresql+asyncpg"):
        _engine_kwargs["connect_args"] = postgres_connect_args(_settings)

def configure_sqlite_engine(sync_engine, *, wal: bool = True) -> None:
    """Make SQLite behave like the production database for transactions.

    * foreign keys are enforced (SQLite ignores them by default);
    * WAL + busy_timeout: API and worker are separate processes sharing the file;
    * explicit BEGIN (SQLAlchemy's documented recipe for pysqlite/aiosqlite). Without it the driver does not
      emit BEGIN before a SAVEPOINT, so RELEASE of the outermost per-agent savepoint silently COMMITS the
      whole transaction: "rolled back" work persisted and fenced-off workers could not be rolled back.
    """

    @event.listens_for(sync_engine, "connect")
    def _on_connect(dbapi_connection, connection_record):
        dbapi_connection.isolation_level = None  # we emit BEGIN ourselves (see _on_begin)
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        if wal:
            cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    @event.listens_for(sync_engine, "begin")
    def _on_begin(conn):
        conn.exec_driver_sql("BEGIN")


engine = create_async_engine(_settings.database_url, **_engine_kwargs)

if _is_sqlite:
    configure_sqlite_engine(engine.sync_engine)

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
