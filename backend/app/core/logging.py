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
import traceback

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


_original_record_factory = logging.getLogRecordFactory()
_factory_installed = False


def _install_stdlib_redaction() -> None:
    """Scrub every stdlib/uvicorn/library log record at creation time.

    A record factory (rather than a handler filter) covers loggers whose
    handlers we do not own, e.g. uvicorn's. The traceback text is rendered
    here, so it is scrubbed after formatting, never before.
    """
    global _factory_installed
    if _factory_installed:
        return

    def factory(*args, **kwargs):
        record = _original_record_factory(*args, **kwargs)
        try:
            record.msg = _scrub_text(record.getMessage())
            record.args = ()
            if record.exc_info and not record.exc_text:
                record.exc_text = _scrub_text("".join(traceback.format_exception(*record.exc_info)).rstrip("\n"))
            elif record.exc_text:
                record.exc_text = _scrub_text(record.exc_text)
            if record.stack_info:
                record.stack_info = _scrub_text(record.stack_info)
        except Exception:  # noqa: BLE001 - logging must never raise
            pass
        return record

    logging.setLogRecordFactory(factory)
    _factory_installed = True


def configure_logging() -> None:
    settings = get_settings()
    _install_stdlib_redaction()
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
        structlog.processors.StackInfoRenderer(),
        # Without this, logger.exception(...)'s exc_info=True is a raw
        # (type, value, traceback) tuple the JSON renderer can't serialize
        # and the traceback would be dropped from the log.
        structlog.processors.format_exc_info,
        # Redaction MUST run after format_exc_info: the rendered traceback
        # text is where secrets embedded in exception messages end up.
        _redact,
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
