"""JSON and human log formatters for F20.

Two formatters implementing logging.Formatter:

- HumanFormatter (default): traditional human-readable format.
- JsonFormatter: one JSON object per log line, suitable for log aggregators.

Selection happens at logging configuration time based on the CRONATOR_LOG_FORMAT
environment variable (or settings.log_format).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

# Fields that the stdlib LogRecord always has; we strip them to keep
# the JSON output focused on what's interesting.
_STD_LOGRECORD_ATTRS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "asctime",
    "message",
    "taskName",
}


class HumanFormatter(logging.Formatter):
    """Default human-readable log format with timestamp + level + name + message."""

    DEFAULT_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"

    def __init__(self) -> None:
        super().__init__(fmt=self.DEFAULT_FORMAT, datefmt=self.DEFAULT_DATEFMT)


class JsonFormatter(logging.Formatter):
    """One JSON object per log line.

    Output shape:
    {
      "timestamp": "2026-09-16T19:30:00.123+00:00",
      "level": "INFO",
      "logger": "cronator.main",
      "message": "Execution finished",
      "module": "executor",
      "line": 412,
      ...extra fields from record...
    }
    """

    def __init__(self, *, json_default: Any = None) -> None:
        super().__init__()
        self._json_default = json_default

    def format(self, record: logging.LogRecord) -> str:
        # Standard fields we always include
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
            "func": record.funcName,
        }

        # Add any extra fields passed via extra={...} or set as attributes
        extras = {
            k: v
            for k, v in record.__dict__.items()
            if k not in _STD_LOGRECORD_ATTRS and not k.startswith("_")
        }
        for k, v in extras.items():
            try:
                json.dumps(v)
                payload[k] = v
            except (TypeError, ValueError):
                payload[k] = repr(v)

        # Exception info, if any
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack_info"] = record.stack_info

        try:
            return json.dumps(payload, default=self._json_default)
        except (TypeError, ValueError) as e:
            # Fall back to a safe string representation so we never crash the logger
            return json.dumps(
                {
                    "timestamp": payload["timestamp"],
                    "level": "ERROR",
                    "logger": payload["logger"],
                    "message": f"log serialization failed: {e}",
                    "original_message": payload["message"],
                }
            )
