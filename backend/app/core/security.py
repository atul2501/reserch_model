"""API authentication and role-based authorization.

Keys are configured as `API_KEYS=name:role:sha256hex[,name:role:sha256hex...]`
so no plaintext credential ever sits in the environment file or in memory
longer than one request. Generate an entry with `python -m scripts.hash_api_key`.

Roles are strictly ordered: viewer < researcher < operator < admin. Read-only
dashboard access (viewer) never grants any control-plane permission.

Fail-closed: with `API_AUTH_REQUIRED=true` (default) and no configured keys,
every protected request is rejected.
"""
from __future__ import annotations

import enum
import hashlib
import hmac
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class Role(enum.IntEnum):
    VIEWER = 1
    RESEARCHER = 2
    OPERATOR = 3
    ADMIN = 4


@dataclass(frozen=True)
class Principal:
    name: str
    role: Role


ANONYMOUS_ADMIN = Principal(name="auth-disabled", role=Role.ADMIN)


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def parse_api_keys(raw: str) -> list[tuple[str, Role, str]]:
    """Returns [(name, role, sha256hex)]. Malformed entries raise ValueError so
    a typo in the environment can never silently downgrade to "no keys"."""
    entries: list[tuple[str, Role, str]] = []
    for chunk in (raw or "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split(":")
        if len(parts) != 3:
            raise ValueError("API_KEYS entries must be name:role:sha256hex")
        name, role_name, digest = (p.strip() for p in parts)
        try:
            role = Role[role_name.upper()]
        except KeyError as exc:
            raise ValueError(f"unknown API role: {role_name!r}") from exc
        if len(digest) != 64 or any(c not in "0123456789abcdefABCDEF" for c in digest):
            raise ValueError("API_KEYS digest must be a 64-char sha256 hex string")
        entries.append((name, role, digest.lower()))
    return entries


def validate_api_keys_config(settings: Settings) -> None:
    """Startup check: a malformed API_KEYS must stop the process with a clear
    error instead of turning every request into an HTTP 500 later."""
    if settings.api_auth_required:
        parse_api_keys(settings.api_keys.get_secret_value())


def authenticate(presented_key: str | None, settings: Settings) -> Principal | None:
    if not presented_key:
        return None
    digest = hash_api_key(presented_key)
    match: Principal | None = None
    try:
        entries = parse_api_keys(settings.api_keys.get_secret_value())
    except ValueError:
        # Fail CLOSED (401), never 500: a broken configuration authenticates nobody.
        logger.error("api.keys_config_invalid", detail="API_KEYS is malformed; rejecting all keys")
        return None
    # Compare against every configured key (constant-time each) so timing does
    # not reveal which entry matched or how many exist.
    for name, role, expected in entries:
        if hmac.compare_digest(digest, expected):
            match = Principal(name=name, role=role)
    return match


class AbuseGuard:
    """In-process brute-force lockout (per client address) and request-rate cap (per principal)."""

    def __init__(self) -> None:
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._locked_until: dict[str, float] = {}
        self._requests: dict[str, deque[float]] = defaultdict(deque)

    def reset(self) -> None:
        self._failures.clear()
        self._locked_until.clear()
        self._requests.clear()

    def locked_seconds(self, client: str, now: float | None = None) -> int:
        now = time.monotonic() if now is None else now
        until = self._locked_until.get(client, 0.0)
        if until <= now:
            self._locked_until.pop(client, None)
            return 0
        return int(until - now) + 1

    def record_failure(self, client: str, settings: Settings, now: float | None = None) -> bool:
        """Returns True when this failure triggers a lockout."""
        now = time.monotonic() if now is None else now
        window = self._failures[client]
        window.append(now)
        while window and window[0] < now - settings.api_auth_failure_window_seconds:
            window.popleft()
        if len(window) >= settings.api_auth_max_failures:
            self._locked_until[client] = now + settings.api_auth_lockout_seconds
            window.clear()
            return True
        return False

    def record_success(self, client: str) -> None:
        self._failures.pop(client, None)

    def over_rate_limit(self, principal: str, settings: Settings, now: float | None = None) -> bool:
        limit = settings.api_rate_limit_per_minute
        if limit <= 0:
            return False
        now = time.monotonic() if now is None else now
        window = self._requests[principal]
        while window and window[0] < now - 60:
            window.popleft()
        if len(window) >= limit:
            return True
        window.append(now)
        return False


abuse_guard = AbuseGuard()


def _client_id(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _extract_key(request: Request) -> str | None:
    header = request.headers.get("x-api-key")
    if header:
        return header.strip()
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def require_role(minimum: Role):
    """FastAPI dependency factory: 401 when unauthenticated, 403 when the
    authenticated principal's role is below `minimum`."""

    async def _dependency(request: Request) -> Principal:
        settings = get_settings()
        if not settings.api_auth_required:
            return ANONYMOUS_ADMIN
        client = _client_id(request)
        locked = abuse_guard.locked_seconds(client)
        if locked:
            logger.warning("api.auth_locked_out", client=client, path=request.url.path, retry_after=locked)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="too many failed authentication attempts",
                headers={"Retry-After": str(locked)},
            )
        principal = authenticate(_extract_key(request), settings)
        if principal is None:
            locked_now = abuse_guard.record_failure(client, settings)
            logger.warning(
                "api.unauthorized", client=client, path=request.url.path, method=request.method,
                key_presented=bool(_extract_key(request)), lockout_triggered=locked_now,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        abuse_guard.record_success(client)
        if abuse_guard.over_rate_limit(principal.name, settings):
            logger.warning("api.rate_limited", principal=principal.name, path=request.url.path)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="rate limit exceeded", headers={"Retry-After": "60"}
            )
        if principal.role < minimum:
            logger.warning(
                "api.forbidden", principal=principal.name, role=principal.role.name, required=minimum.name,
                path=request.url.path,
            )
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient role")
        request.state.principal = principal
        return principal

    return _dependency


viewer_required = Depends(require_role(Role.VIEWER))
researcher_required = Depends(require_role(Role.RESEARCHER))
operator_required = Depends(require_role(Role.OPERATOR))
admin_required = Depends(require_role(Role.ADMIN))
