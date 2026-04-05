"""Unit tests for reliability field validation in Pydantic schemas."""

import pytest
from pydantic import ValidationError

from app.schemas.script import ScriptBase, ScriptCreate, ScriptRead, ScriptUpdate


def _base_valid(**overrides) -> dict:
    """Minimal valid ScriptBase payload."""
    return {
        "name": "test-script",
        "cron_expression": "0 * * * *",
        **overrides,
    }


# ---------------------------------------------------------------------------
# ScriptBase — retry_count
# ---------------------------------------------------------------------------

class TestRetryCount:
    def test_default_is_zero(self):
        s = ScriptBase(**_base_valid())
        assert s.retry_count == 0

    def test_valid_values(self):
        for v in [0, 1, 5, 10]:
            s = ScriptBase(**_base_valid(retry_count=v))
            assert s.retry_count == v

    def test_max_is_ten(self):
        s = ScriptBase(**_base_valid(retry_count=10))
        assert s.retry_count == 10

    def test_above_max_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            ScriptBase(**_base_valid(retry_count=11))
        assert "retry_count" in str(exc_info.value)

    def test_negative_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            ScriptBase(**_base_valid(retry_count=-1))
        assert "retry_count" in str(exc_info.value)


# ---------------------------------------------------------------------------
# ScriptBase — retry_delay
# ---------------------------------------------------------------------------

class TestRetryDelay:
    def test_default_is_60(self):
        s = ScriptBase(**_base_valid())
        assert s.retry_delay == 60

    def test_minimum_is_5(self):
        s = ScriptBase(**_base_valid(retry_delay=5))
        assert s.retry_delay == 5

    def test_below_minimum_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            ScriptBase(**_base_valid(retry_delay=4))
        assert "retry_delay" in str(exc_info.value)

    def test_maximum_is_3600(self):
        s = ScriptBase(**_base_valid(retry_delay=3600))
        assert s.retry_delay == 3600

    def test_above_maximum_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            ScriptBase(**_base_valid(retry_delay=3601))
        assert "retry_delay" in str(exc_info.value)

    def test_valid_midrange(self):
        s = ScriptBase(**_base_valid(retry_delay=300))
        assert s.retry_delay == 300


# ---------------------------------------------------------------------------
# ScriptBase — max_retry_window
# ---------------------------------------------------------------------------

class TestMaxRetryWindow:
    def test_default_is_3600(self):
        s = ScriptBase(**_base_valid())
        assert s.max_retry_window == 3600

    def test_minimum_is_60(self):
        s = ScriptBase(**_base_valid(max_retry_window=60))
        assert s.max_retry_window == 60

    def test_below_minimum_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            ScriptBase(**_base_valid(max_retry_window=59))
        assert "max_retry_window" in str(exc_info.value)

    def test_maximum_is_86400(self):
        s = ScriptBase(**_base_valid(max_retry_window=86400))
        assert s.max_retry_window == 86400

    def test_above_maximum_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            ScriptBase(**_base_valid(max_retry_window=86401))
        assert "max_retry_window" in str(exc_info.value)


# ---------------------------------------------------------------------------
# ScriptBase — prevent_overlap
# ---------------------------------------------------------------------------

class TestPreventOverlap:
    def test_default_is_true(self):
        s = ScriptBase(**_base_valid())
        assert s.prevent_overlap is True

    def test_can_be_set_false(self):
        s = ScriptBase(**_base_valid(prevent_overlap=False))
        assert s.prevent_overlap is False

    def test_explicit_true(self):
        s = ScriptBase(**_base_valid(prevent_overlap=True))
        assert s.prevent_overlap is True


# ---------------------------------------------------------------------------
# ScriptCreate inherits reliability fields
# ---------------------------------------------------------------------------

class TestScriptCreateReliability:
    def test_create_inherits_retry_defaults(self):
        s = ScriptCreate(**_base_valid())
        assert s.retry_count == 0
        assert s.retry_delay == 60
        assert s.max_retry_window == 3600
        assert s.prevent_overlap is True

    def test_create_with_all_reliability_fields(self):
        s = ScriptCreate(**_base_valid(
            retry_count=3,
            retry_delay=120,
            max_retry_window=7200,
            prevent_overlap=False,
        ))
        assert s.retry_count == 3
        assert s.retry_delay == 120
        assert s.max_retry_window == 7200
        assert s.prevent_overlap is False

    def test_create_retry_count_validation_still_applies(self):
        with pytest.raises(ValidationError):
            ScriptCreate(**_base_valid(retry_count=99))


# ---------------------------------------------------------------------------
# ScriptUpdate — all reliability fields are optional
# ---------------------------------------------------------------------------

class TestScriptUpdateReliability:
    def test_empty_update_is_valid(self):
        """ScriptUpdate with no fields is valid (all optional)."""
        s = ScriptUpdate()
        assert s.retry_count is None
        assert s.retry_delay is None
        assert s.max_retry_window is None
        assert s.prevent_overlap is None

    def test_partial_update_retry_count(self):
        s = ScriptUpdate(retry_count=2)
        assert s.retry_count == 2
        assert s.retry_delay is None  # not set

    def test_partial_update_prevent_overlap(self):
        s = ScriptUpdate(prevent_overlap=False)
        assert s.prevent_overlap is False

    def test_update_retry_count_validation(self):
        with pytest.raises(ValidationError):
            ScriptUpdate(retry_count=11)

    def test_update_retry_delay_validation(self):
        with pytest.raises(ValidationError):
            ScriptUpdate(retry_delay=3)

    def test_update_max_retry_window_validation(self):
        with pytest.raises(ValidationError):
            ScriptUpdate(max_retry_window=10)


# ---------------------------------------------------------------------------
# ScriptRead — stats fields present and nullable
# ---------------------------------------------------------------------------

class TestScriptReadStats:
    def _make_read(self, **overrides) -> dict:
        return {
            "id": 1,
            "name": "test-script",
            "cron_expression": "0 * * * *",
            "enabled": True,
            "python_version": "3.12",
            "timeout": 3600,
            "misfire_grace_time": 60,
            "path": "/scripts/test-script/main.py",
            "content": "print('hi')",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            **overrides,
        }

    def test_last_success_at_defaults_to_none(self):
        s = ScriptRead(**self._make_read())
        assert s.last_success_at is None

    def test_last_failure_at_defaults_to_none(self):
        s = ScriptRead(**self._make_read())
        assert s.last_failure_at is None

    def test_consecutive_failures_defaults_to_zero(self):
        s = ScriptRead(**self._make_read())
        assert s.consecutive_failures == 0

    def test_consecutive_failures_can_be_set(self):
        s = ScriptRead(**self._make_read(consecutive_failures=7))
        assert s.consecutive_failures == 7

    def test_last_success_at_can_be_set(self):
        from datetime import UTC, datetime
        now = datetime.now(UTC)
        s = ScriptRead(**self._make_read(last_success_at=now.isoformat()))
        assert s.last_success_at is not None


# ---------------------------------------------------------------------------
# Cross-field logic checks (documented constraints)
# ---------------------------------------------------------------------------

class TestReliabilityConstraintLogic:
    def test_retry_window_should_accommodate_retries(self):
        """
        A sensible config: max_retry_window >= retry_count * retry_delay.
        Pydantic doesn't enforce this cross-field rule, but document it here.
        """
        retry_count = 3
        retry_delay = 120
        max_retry_window = 3600
        # 3 retries * 120s = 360s — fits within 3600s window
        assert retry_count * retry_delay <= max_retry_window

    def test_zero_retry_count_makes_retry_delay_irrelevant(self):
        """When retry_count=0, retry_delay is stored but never used."""
        s = ScriptBase(**_base_valid(retry_count=0, retry_delay=999))
        assert s.retry_count == 0
        # retry_delay is still valid and stored
        assert s.retry_delay == 999
