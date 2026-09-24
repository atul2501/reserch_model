"""OllamaClient — the ONLY place in the codebase allowed to call the Ollama
API (spec section 3). Council, evolution, and post-mortem services all go
through this.

The API is external (not localhost), so this client treats it like any
other third-party HTTP dependency: auth header, timeout, retries with
exponential backoff, bounded concurrency, structured logging with request
ids, and latency tracking. Malformed/unparseable responses are surfaced as
`OllamaResponseError` so callers can fall back to HOLD (spec section 41)
rather than crash.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)

from app.core import metrics
from app.core.config import get_settings
from app.core.logging import get_logger
from app.schemas.normalization import ResponseNormalizationError, normalize_payload, parse_model_json

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


class OllamaError(RuntimeError):
    pass


class OllamaTimeoutError(OllamaError):
    pass


class OllamaRateLimitError(OllamaError):
    pass


class OllamaAuthError(OllamaError):
    """Raised on 401/403. Deliberately retried (see generate_structured's
    @retry decorator) — with multiple OLLAMA_API_KEYS round-robining per
    attempt (see _next_key), a single revoked/expired key must not
    permanently fail every call that happens to land on it; the retry
    exists specifically to rotate onto the next key in the pool instead."""


class OllamaConnectionError(OllamaError):
    """Transport-level failure (connection reset/refused, TLS, DNS): transient, retried with backoff.
    Wrapped so callers never see a raw httpx exception escape the client."""


class OllamaServerError(OllamaError):
    """5xx from the Ollama API: transient, retried with backoff."""


class OllamaUnavailableError(OllamaError):
    """Every configured credential is unhealthy (401/403 or cooling down).
    Raised WITHOUT touching the network so a dead credential costs zero
    cycle time — callers fail closed immediately."""


class OllamaResponseError(OllamaError):
    """Raised when the model's response could not be parsed into the
    expected structured schema — never let this reach the trading engine
    as an unstructured string (spec section 8)."""


@dataclass
class OllamaCallStats:
    request_id: str
    latency_ms: int
    prompt_tokens: int | None
    completion_tokens: int | None
    model: str
    retries: int
    normalization: dict | None = None   # audit of boundary repairs (None when the response needed none)


@dataclass
class OllamaKeyHealth:
    """In-memory credential health. Keys are intentionally never persisted
    or logged. A key that returned 401/403 is UNHEALTHY (`disabled`) until an
    operator calls `OllamaClient.refresh_keys()` — it is never retried on its
    own. A 429 puts it in a bounded, escalating cooldown instead."""
    disabled: bool = False
    disabled_status: int | None = None
    failure_count: int = 0
    cooldown_until: float = 0.0
    last_success: float | None = None
    last_failure: float | None = None


class OllamaClient:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.ollama_base_url:
            logger.warning("ollama.not_configured", detail="OLLAMA_BASE_URL is empty")
        self._base_url = settings.ollama_base_url.rstrip("/")
        # Multiple keys round-robin (see _next_key): every attempt, including
        # retries, picks the next key in rotation, so a 429 on one key gets
        # its retry on a *different* key instead of just backing off on the
        # same rate-limited one.
        self._api_keys = settings.ollama_api_key_list
        self._key_cursor = 0
        self._key_health = [OllamaKeyHealth() for _ in self._api_keys]
        self._model = settings.ollama_model
        self._timeout = settings.ollama_timeout_seconds
        self._max_retries = settings.ollama_max_retries
        self._backoff_min = 1.0   # seconds; tests shrink these
        self._backoff_max = 20.0
        self._semaphore = asyncio.Semaphore(settings.ollama_concurrency)
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout)
        self.last_stats: OllamaCallStats | None = None
        logger.info("ollama.client_initialized", key_count=len(self._api_keys), model=self._model)

    async def aclose(self) -> None:
        await self._client.aclose()

    def _next_key(self) -> tuple[str | None, int | None]:
        """Returns (key, key_index). key_index is the position in
        OLLAMA_API_KEYS (never the key value itself) so auth failures can
        be logged/diagnosed without ever logging a secret."""
        if not self._api_keys:
            return None, None
        now = time.monotonic()
        for _ in range(len(self._api_keys)):
            index = self._key_cursor % len(self._api_keys)
            self._key_cursor += 1
            health = self._key_health[index]
            if not health.disabled and health.cooldown_until <= now:
                return self._api_keys[index], index
        return None, None

    def key_health_snapshot(self) -> list[dict[str, object]]:
        """Safe operational state: positions/statuses only, never secrets."""
        now = time.monotonic()
        return [
            {
                "key_index": index,
                "status": "unhealthy" if h.disabled else ("cooldown" if h.cooldown_until > now else "healthy"),
                "last_error_status": h.disabled_status,
                "failure_count": h.failure_count,
                "last_success_age_s": (now - h.last_success) if h.last_success else None,
                "last_failure_age_s": (now - h.last_failure) if h.last_failure else None,
                "cooldown_remaining_s": max(0.0, h.cooldown_until - now),
            }
            for index, h in enumerate(self._key_health)
        ]

    def is_available(self) -> bool:
        """True if at least one credential could serve a request right now
        (or no credentials are configured, i.e. an open endpoint)."""
        if not self._api_keys:
            return True
        now = time.monotonic()
        return any(not h.disabled and h.cooldown_until <= now for h in self._key_health)

    def has_permanently_failed(self) -> bool:
        return bool(self._api_keys) and all(h.disabled for h in self._key_health)

    def refresh_keys(self, *, force: bool = False) -> dict[str, int]:
        """Re-read credentials from settings WITHOUT a restart.

        A key whose value is unchanged keeps its health (a key that returned 401 stays disabled, so
        a periodic refresh never hammers a known-bad credential); a NEW or replaced key starts healthy.
        `force=True` clears all health state (operator wants every key re-tried). Keys are compared by
        digest and never logged."""
        import hashlib
        from app.core.config import Settings

        def digest(k: str) -> str:
            return hashlib.sha256(k.encode()).hexdigest()

        old = {digest(k): h for k, h in zip(self._api_keys, self._key_health)}
        new_keys = Settings().ollama_api_key_list  # fresh read; never mutates the shared settings cache
        kept = added = 0
        health: list[OllamaKeyHealth] = []
        for k in new_keys:
            previous = None if force else old.get(digest(k))
            if previous is not None:
                kept += 1
            else:
                added += 1
            health.append(previous or OllamaKeyHealth())
        self._api_keys, self._key_health, self._key_cursor = new_keys, health, 0
        logger.info("ollama.keys_refreshed", key_count=len(new_keys), kept=kept, new_or_reset=added, forced=force)
        return {"keys": len(new_keys), "kept": kept, "new_or_reset": added}

    def _mark_success(self, key_index: int | None) -> None:
        if key_index is not None:
            health = self._key_health[key_index]
            health.failure_count = 0
            health.last_success = time.monotonic()

    def _mark_failure(self, key_index: int | None, *, permanent: bool = False, cooldown: float = 0.0) -> None:
        if key_index is not None:
            health = self._key_health[key_index]
            health.failure_count += 1
            health.last_failure = time.monotonic()
            if permanent:
                health.disabled = True  # never cleared implicitly; see refresh_keys()
            health.cooldown_until = max(health.cooldown_until, time.monotonic() + cooldown)

    def _retryable_error(self, exc: BaseException) -> bool:
        # A known-invalid credential is never retried on itself; the retry is
        # only worthwhile if ANOTHER healthy key exists to rotate onto.
        if isinstance(exc, OllamaAuthError):
            return any(not health.disabled for health in self._key_health)
        if isinstance(exc, OllamaRateLimitError):
            return any(not health.disabled and health.cooldown_until <= time.monotonic() for health in self._key_health)
        if isinstance(exc, OllamaUnavailableError):
            return False
        return isinstance(exc, (OllamaTimeoutError, OllamaServerError, OllamaConnectionError, httpx.TransportError))

    @staticmethod
    def _retry_after_seconds(resp: httpx.Response, failure_count: int) -> float:
        """Cooldown for a 429: honour Retry-After (seconds), else an
        escalating default (20s, 40s, 80s ... capped at 120s)."""
        header = resp.headers.get("retry-after")
        if header:
            try:
                return max(1.0, min(120.0, float(header)))
            except ValueError:
                pass
            try:  # RFC 9110 also allows an HTTP-date
                from email.utils import parsedate_to_datetime
                from datetime import datetime, timezone

                when = parsedate_to_datetime(header)
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
                return max(1.0, min(120.0, (when - datetime.now(timezone.utc)).total_seconds()))
            except (TypeError, ValueError):
                pass
        return min(120.0, 20.0 * (2 ** max(0, failure_count - 1)))

    def _headers(self) -> tuple[dict[str, str], int | None]:
        headers = {"Content-Type": "application/json"}
        api_key, key_index = self._next_key()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers, key_index

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
        temperature: float = 0.2,
        max_retries_override: int | None = None,
        deadline_seconds: float | None = None,
    ) -> tuple[T, OllamaCallStats]:
        """Calls Ollama's /api/chat with `format: "json"` and validates the
        result against `response_model`. Raises OllamaResponseError on
        invalid JSON or schema mismatch — callers decide the fallback."""
        if self._api_keys and not self.is_available():
            # Fail closed IMMEDIATELY: no network, no backoff sleeps.
            metrics.inc("ollama_requests", outcome="unavailable")
            raise OllamaUnavailableError(
                "no healthy Ollama credential (all 401/403 or cooling down); refresh_keys() to retry"
            )
        request_id = str(uuid.uuid4())
        max_retries = max_retries_override if max_retries_override is not None else self._max_retries

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "format": "json",
            "stream": False,
            "options": {"temperature": temperature},
        }

        start = time.monotonic()
        retries_used = 0

        async def _attempt() -> dict[str, Any]:
            async with self._semaphore:
                headers, key_index = self._headers()
                headers["X-Request-ID"] = request_id
                if self._api_keys and key_index is None:
                    raise OllamaUnavailableError("no healthy Ollama API key available")
                try:
                    resp = await self._client.post("/api/chat", json=payload, headers=headers)
                except httpx.TimeoutException as exc:
                    metrics.inc("ollama_requests", outcome="timeout")
                    self._mark_failure(key_index)
                    raise OllamaTimeoutError(str(exc)) from exc
                except httpx.TransportError as exc:  # connection reset/refused, TLS, DNS, protocol errors
                    metrics.inc("ollama_requests", outcome="transport_error")
                    self._mark_failure(key_index)
                    raise OllamaConnectionError(f"{type(exc).__name__}: {exc}") from exc
                if resp.status_code == 408:  # request timeout: transient, retryable like a client-side timeout
                    metrics.inc("ollama_requests", outcome="408")
                    self._mark_failure(key_index)
                    raise OllamaTimeoutError("ollama returned 408")
                if resp.status_code == 429:
                    failures = (self._key_health[key_index].failure_count + 1) if key_index is not None else 1
                    self._mark_failure(key_index, cooldown=self._retry_after_seconds(resp, failures))
                    metrics.inc("ollama_requests", outcome="429")
                    raise OllamaRateLimitError("ollama returned 429")
                if 500 <= resp.status_code < 600:
                    self._mark_failure(key_index)
                    metrics.inc("ollama_requests", outcome="5xx")
                    raise OllamaServerError(f"ollama returned {resp.status_code}")
                if resp.status_code in (401, 403):
                    metrics.inc("ollama_requests", outcome=str(resp.status_code))
                    if key_index is not None:
                        self._key_health[key_index].disabled_status = resp.status_code
                    # Bad/expired/revoked key at this index in the
                    # round-robin pool — never log the key itself, only
                    # its position, so ops can find and rotate it out.
                    self._mark_failure(key_index, permanent=True)
                    logger.warning(
                        "ollama.auth_failed_rotating_key",
                        request_id=request_id, status=resp.status_code, key_index=key_index,
                    )
                    raise OllamaAuthError(f"ollama returned {resp.status_code} for key_index={key_index}")
                resp.raise_for_status()
                self._mark_success(key_index)
                try:
                    body = resp.json()
                except ValueError as exc:  # 200 with an HTML/plain-text/empty body (proxy error page, truncation)
                    metrics.inc("ollama_requests", outcome="malformed_envelope")
                    logger.error("ollama.non_json_response", status=resp.status_code, body_prefix=resp.text[:80])
                    raise OllamaResponseError("ollama returned a non-JSON response body") from exc
                metrics.inc("ollama_requests", outcome="ok")
                return body

        @retry(
            reraise=True,
            stop=stop_after_attempt(max(1, max_retries)),
            # Exponential backoff with jitter; a permanently-bad key never gets here (see _retryable_error).
            wait=wait_exponential(multiplier=1, min=self._backoff_min, max=self._backoff_max) + wait_random(0, min(0.5, self._backoff_max)),
            retry=retry_if_exception(self._retryable_error),
        )
        async def _attempt_with_retry() -> dict[str, Any]:
            nonlocal retries_used
            try:
                return await _attempt()
            except (OllamaTimeoutError, OllamaRateLimitError, OllamaAuthError, OllamaServerError, OllamaConnectionError, httpx.TransportError):
                retries_used += 1
                raise

        try:
            if deadline_seconds is not None:
                raw = await asyncio.wait_for(_attempt_with_retry(), timeout=deadline_seconds)
            else:
                raw = await _attempt_with_retry()
        except asyncio.TimeoutError as exc:
            metrics.inc("ollama_requests", outcome="deadline")
            raise OllamaTimeoutError(f"call exceeded its {deadline_seconds}s deadline") from exc
        except httpx.HTTPStatusError as exc:
            logger.error("ollama.http_error", request_id=request_id, status=exc.response.status_code)
            raise OllamaError(f"ollama http error: {exc}") from exc
        except (OllamaTimeoutError, OllamaRateLimitError, OllamaAuthError, OllamaServerError, OllamaConnectionError,
                OllamaUnavailableError, OllamaResponseError) as exc:
            logger.error(
                "ollama.call_failed", request_id=request_id, error=str(exc), retries_used=retries_used,
            )
            raise

        latency_ms = int((time.monotonic() - start) * 1000)
        metrics.observe("ollama_latency_ms", latency_ms)

        message = raw.get("message") if isinstance(raw, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            metrics.inc("ollama_requests", outcome="malformed_envelope")
            logger.error("ollama.malformed_envelope", request_id=request_id)
            raise OllamaResponseError("ollama response has no message content")
        # Boundary: safe parse -> deterministic normalisation (opt-in schemas only) -> STRICT Pydantic validation.
        # A response that cannot be safely normalised is an invalid response, never a partial one.
        report = None
        try:
            parsed_json, parse_method = parse_model_json(content)
            if hasattr(response_model, "ordered_lists"):
                parsed_json, report = normalize_payload(response_model, parsed_json)
                report.parse_method = parse_method
        except ResponseNormalizationError as exc:
            outcome = "malformed_json" if exc.reason == "malformed_json" else "schema_invalid"
            metrics.inc("ollama_requests", outcome=outcome)
            logger.error("ollama.response_rejected", request_id=request_id, model_schema=response_model.__name__,
                         reason=exc.reason, content_prefix=content[:120] if outcome == "malformed_json" else None)
            what = "model did not return valid JSON" if outcome == "malformed_json" else "model response failed schema validation"
            raise OllamaResponseError(f"{what}: {exc.reason}") from exc

        try:
            validated = response_model.model_validate(parsed_json)
        except ValidationError as exc:
            metrics.inc("ollama_requests", outcome="schema_invalid")
            logger.error("ollama.schema_validation_failed", request_id=request_id, model_schema=response_model.__name__,
                         error_count=len(exc.errors()), fields=sorted({str(e["loc"][0]) for e in exc.errors() if e["loc"]}))
            raise OllamaResponseError(f"model response failed schema validation: {str(exc)[:300]}") from exc

        normalization = report.as_dict() if report is not None and report.changed else None
        if normalization is not None:
            for t in report.truncations:
                metrics.inc("ollama_schema_normalized", field=t["field"])
                logger.warning("ollama.schema_normalized", request_id=request_id, model_schema=response_model.__name__,
                               schema_truncated=True, field=t["field"], original_count=t["original_count"],
                               accepted_count=t["accepted_count"], policy=t["policy"])
            if not report.truncations:
                logger.info("ollama.schema_repaired", request_id=request_id, model_schema=response_model.__name__,
                            **{k: v for k, v in normalization.items() if k != "schema_truncated"})

        stats = OllamaCallStats(
            request_id=request_id,
            latency_ms=latency_ms,
            prompt_tokens=raw.get("prompt_eval_count"),
            completion_tokens=raw.get("eval_count"),
            model=self._model,
            retries=retries_used,
            normalization=normalization,
        )
        self.last_stats = stats
        logger.info(
            "ollama.call_succeeded",
            request_id=request_id,
            latency_ms=latency_ms,
            retries=retries_used,
            model=self._model,
        )
        return validated, stats
