# Testing

The backend test suite runs on **Windows** (office PC), **macOS** (personal PC) and **Amazon Linux** (EC2). CI runs the same deterministic suite on Ubuntu (with real PostgreSQL), Windows and macOS (`.github/workflows/ci.yml`).

## Categories

Markers are registered in `backend/pytest.ini` and applied automatically by `backend/tests/conftest.py`.

| Marker | What it needs | Default run? |
|---|---|---|
| `unit` | Nothing external: in-process SQLite, mocked HTTP, no credentials | yes |
| `shadow` | Nothing external (PRETRADE_MODE=shadow and pre-trade architecture tests) | yes |
| `integration` | A **local** service or tool: real PostgreSQL (`TEST_POSTGRES_ADMIN_URL`), Node.js | yes; **skips itself** when the service/tool is absent |
| `performance` | Wall-clock timing; machine-dependent | **no**: `-m performance` |
| `external` | Internet and/or real credentials (Ollama, Hyperliquid, AWS) | **no**: `-m external` (currently no tests use it) |

The default `pytest` run is `-m "not external and not performance"` (set in `pytest.ini`). It needs **none** of: Ollama, internet, Hyperliquid, AWS, credentials, the production database, or EC2.

- Ollama and Hyperliquid are always faked with `httpx.MockTransport` or in-memory fakes in tests.
- The network-guard test blocks every non-loopback socket connection.

## Environment

| Item | Value |
|---|---|
| Python | 3.11 (CI and production target). 3.10 is also exercised locally on the office PC. |
| Install | `pip install -r backend/requirements.txt` |
| Working directory | `backend/` |
| Test database | Set automatically by `tests/conftest.py`: `DATABASE_URL=sqlite+aiosqlite:///./data/test_trading_lab.db`, `TESTING=true`. Relative SQLite paths resolve under `backend/data/` on every OS. |
| PostgreSQL integration (optional) | `TEST_POSTGRES_ADMIN_URL=postgresql://postgres:<pw>@127.0.0.1:55432/postgres`. The tests create and drop their own databases. |
| Node.js (optional) | Needed only for `test_dashboard_js.py` and `test_entry_quality_page.py` |

**Two test runs at once must not share a SQLite file.** For a second, concurrent run, set a different `DATABASE_URL`, e.g. `sqlite+aiosqlite:///./data/test_other.db`. Otherwise both runs fail with "database is locked".

## Commands

### Windows (PowerShell)
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m pytest -q                                   # deterministic suite
python -m pytest -q -m shadow                         # pre-trade / shadow tests only
python -m pytest -q tests\test_paper_execution_v2.py  # paper execution
python -m pytest -q -m performance                    # opt-in timing tests
$env:TEST_POSTGRES_ADMIN_URL = "postgresql://postgres:<pw>@127.0.0.1:55432/postgres"
python -m pytest -q -m integration                    # with a local PostgreSQL
```

### macOS (zsh)
```zsh
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
python -m pytest -q -m shadow
python -m pytest -q tests/test_paper_execution_v2.py
python -m pytest -q -m performance
export TEST_POSTGRES_ADMIN_URL="postgresql://postgres:<pw>@127.0.0.1:55432/postgres"
python -m pytest -q -m integration
```

### Amazon Linux 2023 / EC2 (bash)
```bash
sudo dnf install -y python3.11 python3.11-pip git
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
python -m pytest -q -m shadow
python -m pytest -q -m performance
TEST_POSTGRES_ADMIN_URL="postgresql://postgres:<pw>@127.0.0.1:5432/postgres" python -m pytest -q -m integration
```

**Never** run the test suite with `DATABASE_URL` pointing at the production database. `conftest.py` only *defaults* `DATABASE_URL` to the test SQLite file, so an exported production URL would win.

## Cross-platform rules (what broke before, and the rule now)

| Problem found on Windows | Rule |
|---|---|
| Paths built with `str(path)` compared against `"app/..."` | Compare with `Path.as_posix()`. Build paths with `pathlib`, never by joining `"/"` strings. |
| `resolve_sqlite_url` rewrote absolute URLs (`/` → `\`) | Code fix: absolute URLs are returned unchanged (its documented contract). |
| A network-blocking test patched every `socket.connect` | Block **non-loopback** destinations only. asyncio's Windows event loop uses a 127.0.0.1 `socketpair()` internally. |
| Wall-clock event-loop tests failed on a busy machine | Correctness is proven with a thread handshake (`OffLoopProbe`). The timing versions are `performance` tests with an unchanged threshold. |
| Blocking `git` subprocesses on the event loop | Code fix: provenance is resolved once per process (`warm_provenance_cache()` at research start-up). |
