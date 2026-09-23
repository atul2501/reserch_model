"""All SQLite files live in one folder (backend/data/), independent of the launch directory."""
from __future__ import annotations

from pathlib import Path

from app.core.config import BACKEND_DIR, Settings, resolve_sqlite_url


def test_defaults_point_at_the_single_data_folder(monkeypatch):
    assert Settings.model_fields["database_url"].default == "sqlite+aiosqlite:///./data/trading_lab.db"
    assert Settings.model_fields["database_url_sync"].default == "sqlite:///./data/trading_lab.db"
    # ...and whatever the environment says (tests use data/test_trading_lab.db), it ends up inside backend/data/.
    path = Path(Settings().database_url.split("///", 1)[1])
    assert path.parent == BACKEND_DIR / "data"


def test_relative_path_is_resolved_against_backend_not_the_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)                                   # launch from somewhere unrelated
    url = resolve_sqlite_url("sqlite+aiosqlite:///./data/x.db")
    assert str(BACKEND_DIR / "data" / "x.db") in url
    assert not (tmp_path / "data").exists()                       # nothing created in the CWD
    assert not list(tmp_path.glob("**/*.db"))


def test_parent_folder_is_created():
    target = BACKEND_DIR / "data" / "_probe_dir" / "p.db"
    try:
        resolve_sqlite_url("sqlite:///./data/_probe_dir/p.db")
        assert target.parent.is_dir()
    finally:
        if target.parent.exists():
            target.parent.rmdir()


def test_absolute_memory_and_other_urls_are_untouched(tmp_path):
    absolute = f"sqlite+aiosqlite:///{tmp_path}/abs.db"
    assert resolve_sqlite_url(absolute) == absolute
    assert resolve_sqlite_url("sqlite+aiosqlite:///:memory:") == "sqlite+aiosqlite:///:memory:"
    pg = "postgresql+asyncpg://u:p@h:5432/db"
    assert resolve_sqlite_url(pg) == pg


def test_settings_from_env_use_the_resolved_path(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./data/other.db")
    monkeypatch.setenv("DATABASE_URL_SYNC", "sqlite:///./data/other.db")
    s = Settings()
    assert Path(s.database_url.split("///", 1)[1]) == BACKEND_DIR / "data" / "other.db"
