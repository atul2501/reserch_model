"""Ollama client failure handling: timeout, 429, malformed response (spec 45)."""
from __future__ import annotations

import json

import httpx
import pytest
from pydantic import BaseModel

from app.services.ollama_client import OllamaClient, OllamaResponseError


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
