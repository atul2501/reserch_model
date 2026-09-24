"""Ollama client failure handling (spec phases 14-15): 401, 403, 429, timeout,
5xx, malformed JSON, credential health, no retry of known-bad credentials."""
from __future__ import annotations

import json

import httpx
import pytest
from pydantic import BaseModel

from app.core import metrics
from app.services.ollama_client import (
    OllamaAuthError, OllamaClient, OllamaError, OllamaRateLimitError, OllamaResponseError, OllamaServerError,
    OllamaTimeoutError, OllamaUnavailableError,
)


class Echo(BaseModel):
    value: str


OK = {"message": {"content": json.dumps({"value": "ok"})}, "eval_count": 3}


def make_client(handler, keys=("key-A",), retries=3):
    c = OllamaClient()
    c._api_keys = list(keys)
    from app.services.ollama_client import OllamaKeyHealth
    c._key_health = [OllamaKeyHealth() for _ in keys]
    c._key_cursor = 0
    c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://fake")
    c._max_retries = retries
    c._backoff_min, c._backoff_max = 0.0, 0.01
    return c


async def call(c):
    return await c.generate_structured(system_prompt="s", user_prompt="u", response_model=Echo)


@pytest.fixture(autouse=True)
def _reset_metrics():
    metrics.reset()


async def test_401_single_key_is_not_retried_and_key_is_marked_unhealthy():
    calls = []

    def h(req):
        calls.append(req.headers["authorization"])
        return httpx.Response(401)

    c = make_client(h)
    with pytest.raises(OllamaAuthError):
        await call(c)
    assert len(calls) == 1                                   # a known-invalid key is never retried
    assert c.key_health_snapshot()[0]["status"] == "unhealthy" and c.key_health_snapshot()[0]["last_error_status"] == 401
    assert c.has_permanently_failed() and not c.is_available()
    assert metrics.counter_value("ollama_requests", outcome="401") == 1


async def test_after_a_401_further_calls_fail_fast_without_any_network_call():
    calls = []

    def h(req):
        calls.append(1)
        return httpx.Response(403)

    c = make_client(h)
    with pytest.raises(OllamaAuthError):
        await call(c)
    n = len(calls)
    for _ in range(5):
        with pytest.raises(OllamaUnavailableError):
            await call(c)
    assert len(calls) == n                                   # zero wasted requests / cycle time
    assert c.key_health_snapshot()[0]["last_error_status"] == 403


async def test_403_rotates_to_the_next_healthy_key():
    seen = []

    def h(req):
        seen.append(req.headers["authorization"])
        return httpx.Response(403) if req.headers["authorization"] == "Bearer bad" else httpx.Response(200, json=OK)

    c = make_client(h, keys=("bad", "good"))
    result, stats = await call(c)
    assert result.value == "ok" and stats.retries == 1
    assert seen == ["Bearer bad", "Bearer good"]
    assert [k["status"] for k in c.key_health_snapshot()] == ["unhealthy", "healthy"]
    seen.clear()
    await call(c)
    assert seen == ["Bearer good"]                           # bad key is never used again


async def test_refresh_keys_is_the_only_way_back(monkeypatch):
    def h(req):
        return httpx.Response(401)

    c = make_client(h)
    with pytest.raises(OllamaAuthError):
        await call(c)
    assert not c.is_available()
    monkeypatch.setenv("OLLAMA_API_KEY", "rotated-key")
    monkeypatch.setenv("OLLAMA_API_KEYS", "")
    c.refresh_keys()
    assert c.is_available() and c._api_keys == ["rotated-key"]


async def test_429_respects_retry_after_and_cools_down_only_that_key():
    def h(req):
        if req.headers["authorization"] == "Bearer limited":
            return httpx.Response(429, headers={"retry-after": "37"})
        return httpx.Response(200, json=OK)

    c = make_client(h, keys=("limited", "fine"))
    result, _ = await call(c)
    assert result.value == "ok"
    snap = c.key_health_snapshot()
    assert snap[0]["status"] == "cooldown" and 30 < snap[0]["cooldown_remaining_s"] <= 37
    assert snap[1]["status"] == "healthy"
    assert metrics.counter_value("ollama_requests", outcome="429") == 1


async def test_429_on_the_only_key_fails_fast_no_blind_retry_storm():
    calls = []

    def h(req):
        calls.append(1)
        return httpx.Response(429)

    c = make_client(h)
    with pytest.raises(OllamaRateLimitError):
        await call(c)
    assert len(calls) == 1                                   # key is cooling down: retrying it now would be pointless
    with pytest.raises(OllamaUnavailableError):
        await call(c)                                        # and following calls don't hit the network either
    assert len(calls) == 1


async def test_429_backoff_escalates_without_retry_after():
    r = httpx.Response(429)
    assert OllamaClient._retry_after_seconds(r, 1) == 20 and OllamaClient._retry_after_seconds(r, 2) == 40
    assert OllamaClient._retry_after_seconds(r, 10) == 120
    assert OllamaClient._retry_after_seconds(httpx.Response(429, headers={"retry-after": "5"}), 1) == 5


async def test_timeout_is_retried_then_succeeds():
    n = {"i": 0}

    def h(req):
        n["i"] += 1
        if n["i"] < 3:
            raise httpx.ReadTimeout("slow")
        return httpx.Response(200, json=OK)

    c = make_client(h, retries=3)
    result, stats = await call(c)
    assert result.value == "ok" and stats.retries == 2 and n["i"] == 3


async def test_timeout_exhausts_retries_and_raises_typed_error():
    def h(req):
        raise httpx.ReadTimeout("slow")

    c = make_client(h, retries=2)
    with pytest.raises(OllamaTimeoutError):
        await call(c)
    assert metrics.counter_value("ollama_requests", outcome="timeout") == 2


async def test_5xx_is_retried_with_backoff_and_classified():
    n = {"i": 0}

    def h(req):
        n["i"] += 1
        return httpx.Response(503) if n["i"] < 2 else httpx.Response(200, json=OK)

    c = make_client(h)
    result, stats = await call(c)
    assert result.value == "ok" and stats.retries == 1
    n["i"] = -10
    c2 = make_client(lambda req: httpx.Response(500), retries=2)
    with pytest.raises(OllamaServerError):
        await call(c2)


async def test_malformed_json_and_schema_mismatch_are_typed_and_not_retried():
    calls = []

    def h(req):
        calls.append(1)
        return httpx.Response(200, json={"message": {"content": "<html>not json</html>"}})

    c = make_client(h)
    with pytest.raises(OllamaResponseError):
        await call(c)
    assert len(calls) == 1
    c2 = make_client(lambda req: httpx.Response(200, json={"message": {"content": json.dumps({"nope": 1})}}))
    with pytest.raises(OllamaResponseError):
        await call(c2)


async def test_request_id_is_sent_and_returned_and_secrets_never_logged(capsys):
    sent = {}

    def h(req):
        sent["rid"] = req.headers["x-request-id"]
        return httpx.Response(401)

    c = make_client(h, keys=("super-secret-token-12345",))
    with pytest.raises(OllamaAuthError):
        await call(c)
    assert len(sent["rid"]) == 36
    out = capsys.readouterr().out
    assert "super-secret-token-12345" not in out
    assert "super-secret-token-12345" not in json.dumps(c.key_health_snapshot())


async def test_per_call_deadline_is_enforced():
    import asyncio

    async def slow(req):
        await asyncio.sleep(5)
        return httpx.Response(200, json=OK)

    c = make_client(slow)
    with pytest.raises(OllamaTimeoutError):
        await c.generate_structured(system_prompt="s", user_prompt="u", response_model=Echo, deadline_seconds=0.05)


async def test_concurrency_is_bounded():
    import asyncio
    active = {"now": 0, "max": 0}

    async def h(req):
        active["now"] += 1
        active["max"] = max(active["max"], active["now"])
        await asyncio.sleep(0.02)
        active["now"] -= 1
        return httpx.Response(200, json=OK)

    c = make_client(h)
    c._semaphore = asyncio.Semaphore(3)
    await asyncio.gather(*(call(c) for _ in range(12)))
    assert active["max"] <= 3


async def test_all_ollama_errors_share_a_base_class_so_callers_fail_closed():
    for exc in (OllamaAuthError, OllamaRateLimitError, OllamaTimeoutError, OllamaServerError, OllamaUnavailableError, OllamaResponseError):
        assert issubclass(exc, OllamaError)


# --- full status matrix (spec phase 11): nothing may escape as a raw exception ---------------------------


async def test_200_with_non_json_body_is_a_typed_response_error_not_a_crash():
    c = make_client(lambda req: httpx.Response(200, text="<html>502 proxy error page</html>"))
    with pytest.raises(OllamaResponseError):
        await call(c)
    assert metrics.counter_value("ollama_requests", outcome="malformed_envelope") == 1
    assert c.key_health_snapshot()[0]["status"] == "healthy"   # the key itself is fine


@pytest.mark.parametrize("body", [[1, 2], {"message": None}, {"message": {"content": None}}, {"message": {"content": "  "}}, {}])
async def test_200_with_malformed_envelope_is_a_typed_response_error(body):
    c = make_client(lambda req: httpx.Response(200, json=body))
    with pytest.raises(OllamaResponseError):
        await call(c)


async def test_400_is_not_retried_and_is_a_typed_error():
    calls = []

    def h(req):
        calls.append(1)
        return httpx.Response(400, text="bad request")

    c = make_client(h)
    with pytest.raises(OllamaError):
        await call(c)
    assert len(calls) == 1


async def test_408_is_retried_like_a_timeout_and_can_succeed():
    seq = iter([httpx.Response(408), httpx.Response(200, json=OK)])
    c = make_client(lambda req: next(seq))
    value, stats = await call(c)
    assert value.value == "ok" and stats.retries == 1


@pytest.mark.parametrize("code", [500, 502, 503])
async def test_5xx_is_retried_then_raises_a_typed_server_error(code):
    calls = []

    def h(req):
        calls.append(1)
        return httpx.Response(code)

    c = make_client(h, retries=3)
    with pytest.raises(OllamaServerError):
        await call(c)
    assert len(calls) == 3


async def test_connection_reset_is_wrapped_retried_and_never_escapes_raw():
    from app.services.ollama_client import OllamaConnectionError

    calls = []

    def h(req):
        calls.append(1)
        raise httpx.ReadError("connection reset by peer")

    c = make_client(h, retries=3)
    with pytest.raises(OllamaConnectionError) as exc:
        await call(c)
    assert not isinstance(exc.value, httpx.HTTPError) and len(calls) == 3
    assert metrics.counter_value("ollama_requests", outcome="transport_error") == 3


async def test_connection_reset_then_recovery():
    seq = iter([httpx.ConnectError("refused"), httpx.Response(200, json=OK)])

    def h(req):
        item = next(seq)
        if isinstance(item, Exception):
            raise item
        return item

    value, _ = await call(make_client(h))
    assert value.value == "ok"


async def test_429_retry_after_http_date_is_honoured_and_clamped():
    from datetime import datetime, timedelta, timezone
    from email.utils import format_datetime

    when = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=45), usegmt=True)
    resp = httpx.Response(429, headers={"retry-after": when})
    assert 30 <= OllamaClient._retry_after_seconds(resp, 1) <= 46
    far = format_datetime(datetime.now(timezone.utc) + timedelta(hours=5), usegmt=True)
    assert OllamaClient._retry_after_seconds(httpx.Response(429, headers={"retry-after": far}), 1) == 120.0
    assert OllamaClient._retry_after_seconds(httpx.Response(429, headers={"retry-after": "garbage"}), 2) == 40.0


# --- controlled key refresh ------------------------------------------------------------------------------


def test_refresh_keeps_health_of_unchanged_bad_keys_and_starts_new_keys_healthy(monkeypatch):
    from pydantic import SecretStr
    from app.core.config import Settings

    c = make_client(lambda r: httpx.Response(200, json=OK), keys=("bad-key", "good-key"))
    c._mark_failure(0, permanent=True)
    monkeypatch.setattr(Settings, "ollama_api_key_list", property(lambda self: ["bad-key", "good-key", "rotated-in"]))
    out = c.refresh_keys()
    assert out == {"keys": 3, "kept": 2, "new_or_reset": 1}
    statuses = [k["status"] for k in c.key_health_snapshot()]
    assert statuses == ["unhealthy", "healthy", "healthy"]      # the known-bad key is NOT re-enabled
    assert c.refresh_keys(force=True)["new_or_reset"] == 3       # forced reload re-tests everything
    assert [k["status"] for k in c.key_health_snapshot()] == ["healthy"] * 3


def test_replacing_a_disabled_key_makes_the_client_available_again_without_restart(monkeypatch):
    from app.core.config import Settings

    c = make_client(lambda r: httpx.Response(200, json=OK), keys=("only-key",))
    c._mark_failure(0, permanent=True)
    assert not c.is_available() and c.has_permanently_failed()
    monkeypatch.setattr(Settings, "ollama_api_key_list", property(lambda self: ["replacement-key"]))
    c.refresh_keys()
    assert c.is_available() and not c.has_permanently_failed()


def test_key_refresher_periodic_and_forced(monkeypatch):
    from app.worker.key_refresh import KeyRefresher

    class Fake:
        def __init__(self):
            self.calls = []

        def refresh_keys(self, *, force=False):
            self.calls.append(force)
            return {"keys": 1}

    now = [0.0]
    fake = Fake()
    r = KeyRefresher(fake, interval_seconds=300, clock=lambda: now[0])
    assert r.tick() is None                      # too early
    now[0] = 301
    assert r.tick() == {"keys": 1} and fake.calls == [False]
    assert r.tick() is None
    r.request_forced_refresh()
    assert r.tick() == {"keys": 1} and fake.calls == [False, True]


def test_key_refresher_never_raises_into_the_trading_loop():
    from app.worker.key_refresh import KeyRefresher

    class Boom:
        def refresh_keys(self, *, force=False):
            raise RuntimeError("env file unreadable")

    r = KeyRefresher(Boom(), interval_seconds=0)
    r.request_forced_refresh()
    assert r.tick() is None
