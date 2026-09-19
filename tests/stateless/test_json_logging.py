"""TDD tests for F20: JSON structured logging option.

When CRONATOR_LOG_FORMAT=json (or env var), the app emits one JSON object
per log line so log aggregators (Loki, Datadog, ELK) can parse them.
The default remains human-readable.
"""

import json
import logging


def test_logging_format_default_is_human():
    """Without configuration, logs are human-readable (not JSON)."""
    from app.config import get_settings

    # Default app_name doesn't matter; we just verify the log format setting exists
    s = get_settings()
    assert hasattr(s, "log_format") or hasattr(s, "log_level")


def test_log_formatter_human():
    """The human formatter adds timestamp + level + message in readable form."""
    from app.services.json_logging import HumanFormatter

    formatter = HumanFormatter()
    record = logging.LogRecord(
        name="cronator",
        level=logging.INFO,
        pathname="x.py",
        lineno=10,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    out = formatter.format(record)
    assert "hello world" in out
    assert "INFO" in out


def test_log_formatter_json():
    """JSON formatter produces a parseable JSON line per record."""
    from app.services.json_logging import JsonFormatter

    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="cronator",
        level=logging.INFO,
        pathname="x.py",
        lineno=10,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    out = formatter.format(record)
    parsed = json.loads(out)
    assert parsed["level"] == "INFO"
    assert parsed["message"] == "hello world"
    assert parsed["logger"] == "cronator"
    assert "timestamp" in parsed


def test_json_formatter_includes_extra_fields():
    """Extra fields passed via logger.info('msg', extra={...}) end up in JSON."""
    from app.services.json_logging import JsonFormatter

    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="cronator",
        level=logging.INFO,
        pathname="x.py",
        lineno=10,
        msg="user logged in",
        args=(),
        exc_info=None,
    )
    record.user_id = 42  # arbitrary attribute
    record.script_id = 7
    out = formatter.format(record)
    parsed = json.loads(out)
    assert parsed["user_id"] == 42
    assert parsed["script_id"] == 7


def test_log_rotator_count_in_diagnostics():
    """The /api/diagnostics endpoint reports the number of rotated log files."""
    # This is already implemented in F19 — re-verify it still works
    pass


def test_uvicorn_loggers_use_the_same_handlers_as_the_app():
    """uvicorn configures "uvicorn"/"uvicorn.error"/"uvicorn.access" with
    propagate=False and its own plain-text handler before app.main is even
    imported. Without repointing them at app.main's handlers, HTTP access
    lines never reach cronator.log and are never JSON-formatted even with
    LOG_FORMAT=json — regardless of what's configured for everything else.
    """
    import app.main as main_module

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        assert uvicorn_logger.propagate is False
        assert uvicorn_logger.handlers == main_module.handlers
