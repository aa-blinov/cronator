"""Configurable execution-history retention (app/services/cleanup_service.py).

Retention was a hard-coded constant; operators can now raise it per status via
environment variables without a code change.
"""

import app.main  # noqa: F401 - forces model/db import order before services
from app.services.cleanup_service import RETENTION_BY_STATUS, get_retention_limits

_ALL_ENV = (
    "EXECUTION_RETENTION_SUCCESS",
    "EXECUTION_RETENTION_FAILED",
    "EXECUTION_RETENTION_TIMEOUT",
    "EXECUTION_RETENTION_SKIPPED",
    "EXECUTION_RETENTION_CANCELLED",
)


def _clear(monkeypatch):
    for name in _ALL_ENV:
        monkeypatch.delenv(name, raising=False)


def test_defaults_match_constants(monkeypatch):
    _clear(monkeypatch)
    assert get_retention_limits() == RETENTION_BY_STATUS


def test_env_override(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("EXECUTION_RETENTION_SUCCESS", "1234")
    assert get_retention_limits()["success"] == 1234


def test_invalid_and_nonpositive_overrides_are_ignored(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("EXECUTION_RETENTION_SUCCESS", "not-a-number")
    monkeypatch.setenv("EXECUTION_RETENTION_FAILED", "0")
    limits = get_retention_limits()
    assert limits["success"] == RETENTION_BY_STATUS["success"]
    assert limits["failed"] == RETENTION_BY_STATUS["failed"]
