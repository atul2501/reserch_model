"""Structured logging setup.

All log lines are JSON (when `log_json=True`) and carry a consistent set of
fields so that trading decisions remain auditable (spec section 42 / 32).
Never log secrets: callers must not pass api keys, private keys, or raw
Ollama auth headers into log fields.
"""
from __future__ import annotations

import logging
import re
import sys

import structlog

from app.core.config import get_settings

_REDACT_KEYS = {
    "api_key",
    "private_key",
    "authorization",
    "ollama_api_key",
    "ollama_api_keys",
    "hyperliquid_private_key",
}


_REDACT_KEY_FRAGMENTS = ("api_key", "private_key", "secret", "password", "authorization", "access_token", "auth_token")

# Secret-shaped substrings that can appear inside free text (exception
# messages, URLs, headers echoed by a client library).
_SECRET_PATTERNS = [
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)((?:api[_-]?key|token|secret|password)\s*[=:]\s*)[^\s,;\"']{6,}"),
    re.compile(r"\b0x[a-fA-F0-9]{64}\b"),
]


def _scrub_text(value: str) -> str:
    for pattern in _SECRET_PATTERNS:
        if pattern.groups:
            value = pattern.sub(lambda m: m.group(1) + "***REDACTED***", value)
        else:
            value = pattern.sub("***REDACTED***", value)
    return value


def _is_secret_key(key: object) -> bool:
    lowered = str(key).lower()
    return lowered in _REDACT_KEYS or any(fragment in lowered for fragment in _REDACT_KEY_FRAGMENTS)


def _redact_value(value, depth: int = 0):
    if depth > 6:
        return value
    if isinstance(value, str):
        return _scrub_text(value)
    if isinstance(value, dict):
        return {
            k: ("***REDACTED***" if _is_secret_key(k) else _redact_value(v, depth + 1)) for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return type(value)(_redact_value(v, depth + 1) for v in value)
    return value


def _redact(_, __, event_dict: dict) -> dict:
    for key in list(event_dict.keys()):
        if _is_secret_key(key):
            event_dict[key] = "***REDACTED***"
        else:
            event_dict[key] = _redact_value(event_dict[key])
    return event_dict


def configure_logging() -> None:
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _redact,
        structlog.processors.StackInfoRenderer(),
        # Without this, logger.exception(...)'s exc_info=True is a raw
        # (type, value, traceback) tuple the JSON renderer can't serialize
        # — it was silently degrading to the literal string/bool "true"
        # with the actual exception and traceback dropped entirely. This
        # is why "cycle.unhandled_error" never carried a traceback: it
        # never made it into the log at all, not even for a human to grep.
        structlog.processors.format_exc_info,
    ]

    if settings.log_json:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
