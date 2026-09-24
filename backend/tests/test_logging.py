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


def test_traceback_text_is_redacted_after_formatting(capsys):
    """The traceback string is produced by format_exc_info; redaction must run
    AFTER it or secrets embedded in exception messages leak into the log."""
    configure_logging()
    logger = get_logger(__name__)
    fake_key = "0x" + "ab" * 32

    try:
        raise RuntimeError(f"signing failed key={fake_key} Authorization: Bearer abcdefgh12345678")
    except RuntimeError:
        logger.exception("test.leaky_exception")

    out = capsys.readouterr().out
    payload = json.loads(out.strip().splitlines()[-1])
    assert fake_key not in payload["exception"]
    assert "abcdefgh12345678" not in payload["exception"]
    assert "RuntimeError" in payload["exception"]
    assert fake_key not in out


def test_stdlib_and_uvicorn_loggers_are_redacted():
    import io
    import logging

    configure_logging()
    fake_key = "0x" + "cd" * 32
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(logging.Formatter("%(message)s"))
    targets = [logging.getLogger("uvicorn.error"), logging.getLogger("some.lib")]
    for lg in targets:
        lg.addHandler(handler)
    try:
        logging.getLogger("uvicorn.error").error("boom %s", fake_key)
        try:
            raise RuntimeError(f"secret={fake_key}")
        except RuntimeError:
            logging.getLogger("some.lib").exception("lib failure")
    finally:
        for lg in targets:
            lg.removeHandler(handler)

    text = buf.getvalue()
    assert "boom" in text and "RuntimeError" in text
    assert fake_key not in text
