"""structlog configuration: logger.exception(...) must actually carry a
formatted traceback in the log output, not silently drop it.

Regression guard for a real production bug: the processor chain was
missing structlog.processors.format_exc_info, so exc_info=True (what
logger.exception sets) reached the JSON renderer as a raw, unserializable
(type, value, traceback) tuple and degraded to the literal string "true" —
every "cycle.unhandled_error" log line in production carried zero
information about what actually failed."""
from __future__ import annotations

import json

import structlog

from app.core.logging import configure_logging, get_logger


def test_logger_exception_includes_a_real_traceback(capsys):
    configure_logging()
    logger = get_logger(__name__)

    try:
        raise ValueError("boom")
    except ValueError:
        logger.exception("test.something_failed")

    captured = capsys.readouterr()
    # log_json defaults to True (see Settings.log_json) in this test env,
    # so the line should be valid JSON with a real traceback string.
    line = captured.out.strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["event"] == "test.something_failed"
    assert "exception" in payload
    assert "ValueError: boom" in payload["exception"]
    assert "Traceback (most recent call last)" in payload["exception"]
