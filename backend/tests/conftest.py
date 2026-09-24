from __future__ import annotations

import os

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./data/test_trading_lab.db")
os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434")
os.environ.setdefault("OLLAMA_MODEL", "test-model")
# Unit tests run against DETERMINISTIC execution: the production realism defaults (random rejects, partial fills,
# latency drift, $10 minimum order) are pinned off here and switched on explicitly by the tests that cover them.
# tests/test_paper_realism.py asserts the production defaults from the Settings class itself.
os.environ.setdefault("PAPER_REJECT_PROBABILITY", "0")
os.environ.setdefault("PAPER_PARTIAL_FILL_PROBABILITY", "0")
os.environ.setdefault("PAPER_LATENCY_DRIFT_BPS_PER_SEC", "0")
os.environ.setdefault("PAPER_MIN_ORDER_NOTIONAL", "0")
os.environ.setdefault("TRAILING_STOP_USES_SAME_BAR_EXTREME", "false")   # unit tests pin the legacy rule; the default rule has its own tests

from app.core.database import Base  # noqa: E402
import app.models  # noqa: E402,F401


@pytest_asyncio.fixture
async def db_engine():
    """The async engine behind `db_session` (tests that need extra independent sessions use it)."""
    from app.core.config import get_settings

    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    if settings.database_url.startswith("sqlite"):
        # Same transactional behaviour as production: enforced FKs and real SAVEPOINT/ROLLBACK semantics.
        from app.core.database import configure_sqlite_engine

        configure_sqlite_engine(engine.sync_engine, wal=False)

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


@pytest.fixture(autouse=True)
def _reset_api_abuse_guard():
    from app.core.security import abuse_guard

    abuse_guard.reset()
    yield
    abuse_guard.reset()


@pytest.fixture
def immediate_fills(monkeypatch):
    """Legacy/shadow-style execution: an order fills on the signal bar's own close.

    Position-mechanics tests (stops, funding, liquidation, cooldown, isolation) are independent of fill timing and
    use this to open positions in one cycle. The production default (`next_open`: fill at the next bar's open) is
    covered by tests/test_next_open_execution.py and the parity tests."""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "paper_fill_timing", "signal_close")
