"""Ollama client failure handling: timeout, 429, malformed response (spec 45)."""
from __future__ import annotations

import json

import httpx
import pytest
from pydantic import BaseModel

from app.services.ollama_client import OllamaAuthError, OllamaClient, OllamaResponseError


class _Echo(BaseModel):
    value: str


def _mock_transport(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://fake-ollama")


@pytest.mark.asyncio
async def test_valid_response_is_parsed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"content": json.dumps({"value": "ok"})}, "eval_count": 10})

    client = OllamaClient()
    client._client = _mock_transport(handler)
    result, stats = await client.generate_structured(system_prompt="s", user_prompt="u", response_model=_Echo)
    assert result.value == "ok"
    assert stats.completion_tokens == 10


@pytest.mark.asyncio
async def test_invalid_json_raises_response_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"content": "not json at all"}})

    client = OllamaClient()
    client._client = _mock_transport(handler)
    with pytest.raises(OllamaResponseError):
        await client.generate_structured(system_prompt="s", user_prompt="u", response_model=_Echo)


@pytest.mark.asyncio
async def test_schema_mismatch_raises_response_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"content": json.dumps({"wrong_field": 1})}})

    client = OllamaClient()
    client._client = _mock_transport(handler)
    with pytest.raises(OllamaResponseError):
        await client.generate_structured(system_prompt="s", user_prompt="u", response_model=_Echo)


@pytest.mark.asyncio
async def test_429_is_retried_then_raises_after_exhausting_retries():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(429)

    client = OllamaClient()
    client._client = _mock_transport(handler)
    client._max_retries = 2
    with pytest.raises(Exception):
        await client.generate_structured(system_prompt="s", user_prompt="u", response_model=_Echo)
    assert calls["count"] == 2


@pytest.mark.asyncio
async def test_timeout_is_retried_then_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    client = OllamaClient()
    client._client = _mock_transport(handler)
    client._max_retries = 2
    with pytest.raises(Exception):
        await client.generate_structured(system_prompt="s", user_prompt="u", response_model=_Echo)


@pytest.mark.asyncio
async def test_401_on_one_key_is_retried_and_recovers_on_the_next_key():
    """Root cause of the reported intermittent analyst 401s: with multiple
    OLLAMA_API_KEYS round-robining per attempt, a single bad/expired key
    must not permanently fail a call — the retry must rotate onto the next
    (good) key and succeed, not fail immediately on the first 401."""
    calls = {"count": 0, "auth_headers_seen": []}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        auth = request.headers.get("Authorization")
        calls["auth_headers_seen"].append(auth)
        if auth == "Bearer bad-key":
            return httpx.Response(401)
        return httpx.Response(200, json={"message": {"content": json.dumps({"value": "ok"})}})

    client = OllamaClient()
    client._client = _mock_transport(handler)
    client._api_keys = ["bad-key", "good-key"]
    client._max_retries = 3

    result, stats = await client.generate_structured(system_prompt="s", user_prompt="u", response_model=_Echo)

    assert result.value == "ok"
    assert calls["count"] == 2  # first attempt (bad-key, 401) + retry (good-key, 200)
    assert calls["auth_headers_seen"] == ["Bearer bad-key", "Bearer good-key"]
    assert stats.retries == 1


@pytest.mark.asyncio
async def test_401_on_every_key_exhausts_retries_and_raises_auth_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    client = OllamaClient()
    client._client = _mock_transport(handler)
    client._api_keys = ["bad-key-1", "bad-key-2"]
    client._max_retries = 2

    with pytest.raises(OllamaAuthError):
        await client.generate_structured(system_prompt="s", user_prompt="u", response_model=_Echo)
