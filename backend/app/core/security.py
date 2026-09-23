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


def authenticate(presented_key: str | None, settings: Settings) -> Principal | None:
    if not presented_key:
        return None
    digest = hash_api_key(presented_key)
    match: Principal | None = None
    # Compare against every configured key (constant-time each) so timing does
    # not reveal which entry matched or how many exist.
    for name, role, expected in parse_api_keys(settings.api_keys):
        if hmac.compare_digest(digest, expected):
            match = Principal(name=name, role=role)
    return match


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
        principal = authenticate(_extract_key(request), settings)
        if principal is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="authentication required",
                headers={"WWW-Authenticate": "Bearer"},
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
