"""Structured logging setup.

All log lines are JSON (when `log_json=True`) and carry a consistent set of
fields so that trading decisions remain auditable (spec section 42 / 32).
Never log secrets: callers must not pass api keys, private keys, or raw
Ollama auth headers into log fields.
"""
from __future__ import annotations

import logging
import sys

import structlog

from app.core.config import get_settings

_REDACT_KEYS = {"api_key", "private_key", "authorization", "ollama_api_key", "hyperliquid_private_key"}


def _redact(_, __, event_dict: dict) -> dict:
    for key in list(event_dict.keys()):
        if key.lower() in _REDACT_KEYS:
            event_dict[key] = "***REDACTED***"
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
