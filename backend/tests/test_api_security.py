"""API authentication / authorization, kill switch, log redaction (spec
sections 33/34). Auth must fail closed and viewer keys must never reach
control-plane endpoints."""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio

from app.core.config import get_settings
from app.core.database import get_db
from app.core.logging import _redact
from app.core.security import Role, hash_api_key, parse_api_keys
from app.core.system_flags import KILL_SWITCH, trading_halt_reason
from app.main import create_app

VIEWER_KEY = "viewer-secret-key"
OPERATOR_KEY = "operator-secret-key"


def _keys() -> str:
    return f"v:viewer:{hash_api_key(VIEWER_KEY)},o:operator:{hash_api_key(OPERATOR_KEY)}"


@pytest_asyncio.fixture
async def client(db_session, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "api_auth_required", True)
    monkeypatch.setattr(settings, "api_keys", _keys())
    app = create_app()

    async def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_missing_key_is_401(client):
    assert (await client.get("/api/population")).status_code == 401


async def test_wrong_key_is_401(client):
    assert (await client.get("/api/population", headers={"X-API-Key": "nope"})).status_code == 401


async def test_viewer_key_can_read(client):
    r = await client.get("/api/system/flags", headers={"X-API-Key": VIEWER_KEY})
    assert r.status_code == 200
    r = await client.get("/api/system/flags", headers={"Authorization": f"Bearer {VIEWER_KEY}"})
    assert r.status_code == 200


async def test_viewer_cannot_use_kill_switch(client):
    r = await client.post("/api/system/kill-switch", json={"active": True}, headers={"X-API-Key": VIEWER_KEY})
    assert r.status_code == 403


async def test_operator_kill_switch_blocks_new_entries(client, db_session):
    r = await client.post(
        "/api/system/kill-switch", json={"active": True, "reason": "drill"}, headers={"X-API-Key": OPERATOR_KEY}
    )
    assert r.status_code == 200
    assert await trading_halt_reason(db_session) == KILL_SWITCH
    r = await client.post("/api/system/kill-switch", json={"active": False}, headers={"X-API-Key": OPERATOR_KEY})
    assert r.status_code == 200
    assert await trading_halt_reason(db_session) is None


async def test_auth_required_without_configured_keys_fails_closed(db_session, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "api_auth_required", True)
    monkeypatch.setattr(settings, "api_keys", "")
    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get("/api/population", headers={"X-API-Key": "anything"})).status_code == 401


async def test_livez_is_public_and_data_free(client):
    r = await client.get("/livez")
    assert r.status_code == 200 and r.json() == {"status": "alive"}


async def test_security_headers_and_restricted_cors(client):
    r = await client.get("/livez")
    assert r.headers["x-content-type-options"] == "nosniff"
    pre = await client.options(
        "/api/population",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in pre.headers


def test_parse_api_keys_rejects_malformed_entries():
    with pytest.raises(ValueError):
        parse_api_keys("just-a-key")
    with pytest.raises(ValueError):
        parse_api_keys("x:superuser:" + "a" * 64)
    with pytest.raises(ValueError):
        parse_api_keys("x:viewer:tooshort")
    assert parse_api_keys(f"x:admin:{'a' * 64}")[0][1] == Role.ADMIN


def test_default_bind_is_loopback():
    # The *code* default, independent of any developer's local .env.
    from app.core.config import Settings
    assert Settings.model_fields["api_host"].default == "127.0.0.1"


def test_log_redaction_scrubs_keys_nested_values_and_free_text():
    out = _redact(None, None, {
        "event": "x",
        "ollama_api_keys": "k1,k2",
        "nested": {"api_key": "zzz", "ok": 1},
        "error": "401 Bearer abcdef1234567890abcdef",
        "wallet": "0x" + "a" * 64,
        "prompt_tokens": 12,
    })
    assert out["ollama_api_keys"] == "***REDACTED***"
    assert out["nested"] == {"api_key": "***REDACTED***", "ok": 1}
    assert "abcdef1234567890" not in out["error"]
    assert out["wallet"] == "***REDACTED***"
    assert out["prompt_tokens"] == 12  # token *counts* are not secrets


def test_every_key_in_env_example_is_a_real_setting():
    """A typo'd or stale variable in .env.example would silently do nothing in production."""
    from pathlib import Path
    from app.core.config import Settings
    text = (Path(__file__).resolve().parents[2] / ".env.example").read_text()
    known = {n.upper() for n in Settings.model_fields} | {"DATABASE_URL_SYNC"}
    keys = [ln.split("=", 1)[0].strip() for ln in text.splitlines() if ln and not ln.startswith("#") and "=" in ln]
    assert keys
    legacy_ok = {"HYPERLIQUID_WALLET_ADDRESS"}
    unknown = [k for k in keys if k not in known and k not in legacy_ok]
    assert unknown == [], unknown
