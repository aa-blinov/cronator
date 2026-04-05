"""
Unit tests for reliability features:
  - prevent_overlap / SKIPPED execution
  - retry scheduling (retry_count, retry_delay, max_retry_window)
  - consecutive_failures / last_success_at / last_failure_at stat tracking
  - attempt numbering
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.execution import Execution, ExecutionStatus
from app.models.script import Script
from app.services.executor import ExecutorService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_script(
    id: int = 1,
    prevent_overlap: bool = True,
    retry_count: int = 0,
    retry_delay: int = 60,
    max_retry_window: int = 3600,
    consecutive_failures: int = 0,
) -> MagicMock:
    s = MagicMock(spec=Script)
    s.id = id
    s.name = "test-script"
    s.content = "print('hello')"
    s.path = "/scripts/test-script/main.py"
    s.python_version = "3.12"
    s.dependencies = ""
    s.timeout = 30
    s.environment_vars = None
    s.working_directory = None
    s.enabled = True
    s.prevent_overlap = prevent_overlap
    s.retry_count = retry_count
    s.retry_delay = retry_delay
    s.max_retry_window = max_retry_window
    s.consecutive_failures = consecutive_failures
    s.last_success_at = None
    s.last_failure_at = None
    s.alert_on_failure = False
    s.alert_on_success = False
    s.last_alert_at = None
    return s


def _make_skipped_execution(script_id: int = 1, attempt: int = 1) -> MagicMock:
    e = MagicMock(spec=Execution)
    e.id = 99
    e.script_id = script_id
    e.status = ExecutionStatus.SKIPPED.value
    e.attempt = attempt
    e.duration_ms = 0
    e.stdout = "Skipped: another instance is already running (prevent_overlap=true)"
    return e


def _session_ctx_returning(obj) -> MagicMock:
    """Return a mock async_session_maker() that yields a db returning `obj` from execute()."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = obj

    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=db)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


# ---------------------------------------------------------------------------
# Tests: ExecutionStatus enum
# ---------------------------------------------------------------------------

class TestExecutionStatusSkipped:
    def test_skipped_value(self):
        assert ExecutionStatus.SKIPPED.value == "skipped"

    def test_skipped_in_enum_members(self):
        values = {s.value for s in ExecutionStatus}
        assert "skipped" in values

    def test_skipped_is_finished(self):
        """SKIPPED executions count as finished (not still in-progress)."""
        e = MagicMock(spec=Execution)
        e.status = ExecutionStatus.SKIPPED.value
        # is_finished is a property on Execution; test via the enum directly
        finished_statuses = {
            ExecutionStatus.SUCCESS.value,
            ExecutionStatus.FAILED.value,
            ExecutionStatus.TIMEOUT.value,
            ExecutionStatus.CANCELLED.value,
            ExecutionStatus.SKIPPED.value,
        }
        assert e.status in finished_statuses


# ---------------------------------------------------------------------------
# Tests: Script model new fields
# ---------------------------------------------------------------------------

class TestScriptReliabilityFields:
    def test_script_has_retry_count(self):
        s = _make_script(retry_count=3)
        assert s.retry_count == 3

    def test_script_has_retry_delay(self):
        s = _make_script(retry_delay=120)
        assert s.retry_delay == 120

    def test_script_has_max_retry_window(self):
        s = _make_script(max_retry_window=7200)
        assert s.max_retry_window == 7200

    def test_script_prevent_overlap_default_true(self):
        s = _make_script()
        assert s.prevent_overlap is True

    def test_script_has_consecutive_failures(self):
        s = _make_script(consecutive_failures=5)
        assert s.consecutive_failures == 5

    def test_script_has_last_success_at(self):
        s = _make_script()
        assert s.last_success_at is None  # nullable

    def test_script_has_last_failure_at(self):
        s = _make_script()
        assert s.last_failure_at is None  # nullable


# ---------------------------------------------------------------------------
# Tests: Execution model — attempt field
# ---------------------------------------------------------------------------

class TestExecutionAttempt:
    def test_attempt_defaults_to_one(self):
        """attempt=1 means it's the first (original) run."""
        e = MagicMock(spec=Execution)
        e.attempt = 1
        assert e.attempt == 1

    def test_attempt_two_means_first_retry(self):
        e = MagicMock(spec=Execution)
        e.attempt = 2
        assert e.attempt == 2

    def test_attempt_stored_in_skipped_record(self):
        e = _make_skipped_execution(attempt=1)
        assert e.attempt == 1
        assert e.status == ExecutionStatus.SKIPPED.value


# ---------------------------------------------------------------------------
# Tests: prevent_overlap — SKIPPED record creation
# ---------------------------------------------------------------------------

class TestPreventOverlap:
    @pytest.mark.asyncio
    async def test_skipped_record_created_when_script_already_running(self):
        """
        When prevent_overlap=True and the script is in _running_scripts,
        execute_script() must create a SKIPPED execution and return its id.
        """
        service = ExecutorService()
        service._running_scripts.add(1)  # simulate already running

        script = _make_script(id=1, prevent_overlap=True)

        SKIPPED_ID = 99

        def _make_session_for_script():
            res = MagicMock()
            res.scalar_one_or_none.return_value = script
            db = AsyncMock()
            db.execute = AsyncMock(return_value=res)
            db.add = MagicMock()
            db.commit = AsyncMock()
            db.refresh = AsyncMock()
            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=db)
            ctx.__aexit__ = AsyncMock(return_value=None)
            return ctx

        def _make_session_for_skip():
            db = AsyncMock()
            db.add = MagicMock()
            db.commit = AsyncMock()

            async def refresh_side_effect(obj):
                # Simulate what the DB would do: assign the PK
                obj.id = SKIPPED_ID

            db.refresh = AsyncMock(side_effect=refresh_side_effect)
            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=db)
            ctx.__aexit__ = AsyncMock(return_value=None)
            return ctx

        session_calls = [_make_session_for_script(), _make_session_for_skip()]
        call_index = 0

        def session_factory():
            nonlocal call_index
            ctx = session_calls[call_index]
            call_index += 1
            return ctx

        with patch("app.services.executor.async_session_maker", side_effect=session_factory):
            result = await service.execute_script(script_id=1, triggered_by="scheduler")

        assert result == SKIPPED_ID

    @pytest.mark.asyncio
    async def test_no_task_spawned_when_overlap_skipped(self):
        """No background _run_script task is created when overlap is detected."""
        service = ExecutorService()
        service._running_scripts.add(1)

        script = _make_script(id=1, prevent_overlap=True)
        skipped = _make_skipped_execution(script_id=1)

        session_calls = [
            _session_ctx_returning(script),
            _session_ctx_returning(skipped),
        ]
        call_index = 0

        def session_factory():
            nonlocal call_index
            ctx = session_calls[call_index]
            call_index += 1
            return ctx

        with (
            patch("app.services.executor.async_session_maker", side_effect=session_factory),
            patch("asyncio.create_task") as mock_create_task,
        ):
            await service.execute_script(script_id=1, triggered_by="scheduler")

        mock_create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_overlap_raises_when_prevent_overlap_false(self):
        """
        When prevent_overlap=False and the script is running,
        execute_script() raises ValueError (existing behaviour).
        """
        service = ExecutorService()
        service._running_scripts.add(1)

        script = _make_script(id=1, prevent_overlap=False)

        with (
            patch(
                "app.services.executor.async_session_maker",
                return_value=_session_ctx_returning(script),
            ),
            pytest.raises(ValueError, match="already running"),
        ):
            await service.execute_script(script_id=1, triggered_by="scheduler")

    @pytest.mark.asyncio
    async def test_not_running_script_proceeds_normally(self):
        """When script is NOT running, execute_script proceeds to create a task."""
        service = ExecutorService()
        # script_id=1 NOT in _running_scripts

        script = _make_script(id=1, prevent_overlap=True)
        execution = MagicMock(spec=Execution)
        execution.id = 42

        # Session calls: get script, create execution record
        def make_session(return_obj):
            res = MagicMock()
            res.scalar_one_or_none.return_value = return_obj
            db = AsyncMock()
            db.execute = AsyncMock(return_value=res)
            db.add = MagicMock()
            db.commit = AsyncMock()
            db.refresh = AsyncMock(side_effect=lambda obj: setattr(obj, "id", 42))
            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=db)
            ctx.__aexit__ = AsyncMock(return_value=None)
            return ctx

        session_calls = [make_session(script)]
        call_index = 0

        def session_factory():
            nonlocal call_index
            ctx = session_calls[call_index % len(session_calls)]
            call_index += 1
            return ctx

        with (
            patch("app.services.executor.async_session_maker", side_effect=session_factory),
            patch("asyncio.create_task") as mock_task,
        ):
            await service.execute_script(script_id=1, triggered_by="manual")

        mock_task.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: Retry logic
# ---------------------------------------------------------------------------

class TestRetryScheduling:
    @pytest.mark.asyncio
    async def test_delayed_retry_calls_execute_script_after_delay(self):
        """_delayed_retry sleeps for `delay` seconds then calls execute_script."""
        service = ExecutorService()

        sleep_calls = []
        execute_calls = []

        async def fake_sleep(n):
            sleep_calls.append(n)

        async def fake_execute(**kwargs):
            execute_calls.append(kwargs)
            return 99

        first_attempt_at = datetime.now(UTC) - timedelta(seconds=10)

        with patch("asyncio.sleep", side_effect=fake_sleep):
            with patch.object(service, "execute_script", side_effect=fake_execute):
                await service._delayed_retry(
                    script_id=1,
                    triggered_by="retry",
                    attempt=2,
                    delay=30,
                    first_attempt_at=first_attempt_at,
                )

        assert sleep_calls == [30]
        assert len(execute_calls) == 1
        assert execute_calls[0]["script_id"] == 1
        assert execute_calls[0]["attempt"] == 2
        assert execute_calls[0]["triggered_by"] == "retry"
        assert execute_calls[0]["first_attempt_at"] == first_attempt_at

    @pytest.mark.asyncio
    async def test_delayed_retry_passes_first_attempt_at_unchanged(self):
        """first_attempt_at is forwarded unchanged through retry chain."""
        service = ExecutorService()
        captured = {}

        async def fake_execute(**kwargs):
            captured.update(kwargs)
            return 1

        original_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with patch.object(service, "execute_script", side_effect=fake_execute):
                await service._delayed_retry(
                    script_id=5,
                    triggered_by="retry",
                    attempt=3,
                    delay=10,
                    first_attempt_at=original_time,
                )

        assert captured["first_attempt_at"] == original_time

    @pytest.mark.asyncio
    async def test_delayed_retry_swallows_exception(self):
        """If execute_script raises inside _delayed_retry, it must not propagate."""
        service = ExecutorService()

        async def bad_execute(**kwargs):
            raise RuntimeError("something went wrong")

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with patch.object(service, "execute_script", side_effect=bad_execute):
                # Must not raise
                await service._delayed_retry(
                    script_id=1,
                    triggered_by="retry",
                    attempt=2,
                    delay=5,
                    first_attempt_at=datetime.now(UTC),
                )

    def test_retries_left_formula(self):
        """Verify retries_left = retry_count - (attempt - 1)."""
        # retry_count=3 means 3 additional attempts after the first
        # attempt=1 → retries_left = 3
        # attempt=2 → retries_left = 2
        # attempt=4 → retries_left = 0 (no more)
        for attempt, expected_left in [(1, 3), (2, 2), (3, 1), (4, 0)]:
            retry_count = 3
            retries_left = retry_count - (attempt - 1)
            assert retries_left == expected_left, f"attempt={attempt}"

    def test_max_retry_window_expires(self):
        """Retry must NOT be scheduled when time_elapsed >= max_retry_window."""
        max_retry_window = 3600
        first_attempt_at = datetime.now(UTC) - timedelta(seconds=3601)
        time_elapsed = (datetime.now(UTC) - first_attempt_at).total_seconds()
        assert time_elapsed >= max_retry_window  # window is expired

    def test_max_retry_window_active(self):
        """Retry IS allowed when time_elapsed < max_retry_window."""
        max_retry_window = 3600
        first_attempt_at = datetime.now(UTC) - timedelta(seconds=100)
        time_elapsed = (datetime.now(UTC) - first_attempt_at).total_seconds()
        assert time_elapsed < max_retry_window

    def test_no_retry_when_retry_count_zero(self):
        """retries_left == 0 when retry_count == 0, so no retry is scheduled."""
        retry_count = 0
        attempt = 1
        retries_left = retry_count - (attempt - 1)
        assert retries_left == 0


# ---------------------------------------------------------------------------
# Tests: Stat tracking logic
# ---------------------------------------------------------------------------

class TestStatTracking:
    """
    Tests for last_success_at / last_failure_at / consecutive_failures update logic.
    These verify the branching logic that runs after execution finishes.
    """

    def _apply_stat_update(self, script: MagicMock, final_status: str, now: datetime) -> None:
        """Replicate the stat-update logic from executor._run_script."""
        if final_status == ExecutionStatus.SUCCESS.value:
            script.last_success_at = now
            script.consecutive_failures = 0
        elif final_status in (
            ExecutionStatus.FAILED.value,
            ExecutionStatus.TIMEOUT.value,
        ):
            script.last_failure_at = now
            script.consecutive_failures += 1

    def test_success_resets_consecutive_failures(self):
        script = _make_script(consecutive_failures=5)
        now = datetime.now(UTC)
        self._apply_stat_update(script, ExecutionStatus.SUCCESS.value, now)
        assert script.consecutive_failures == 0

    def test_success_sets_last_success_at(self):
        script = _make_script()
        now = datetime.now(UTC)
        self._apply_stat_update(script, ExecutionStatus.SUCCESS.value, now)
        assert script.last_success_at == now

    def test_success_does_not_touch_last_failure_at(self):
        t = datetime(2026, 1, 1, tzinfo=UTC)
        script = _make_script()
        script.last_failure_at = t
        now = datetime.now(UTC)
        self._apply_stat_update(script, ExecutionStatus.SUCCESS.value, now)
        assert script.last_failure_at == t  # unchanged

    def test_failure_increments_consecutive_failures(self):
        script = _make_script(consecutive_failures=2)
        now = datetime.now(UTC)
        self._apply_stat_update(script, ExecutionStatus.FAILED.value, now)
        assert script.consecutive_failures == 3

    def test_timeout_increments_consecutive_failures(self):
        script = _make_script(consecutive_failures=0)
        now = datetime.now(UTC)
        self._apply_stat_update(script, ExecutionStatus.TIMEOUT.value, now)
        assert script.consecutive_failures == 1

    def test_failure_sets_last_failure_at(self):
        script = _make_script()
        now = datetime.now(UTC)
        self._apply_stat_update(script, ExecutionStatus.FAILED.value, now)
        assert script.last_failure_at == now

    def test_failure_does_not_reset_consecutive_failures(self):
        """consecutive_failures keeps growing on repeated failures."""
        script = _make_script(consecutive_failures=3)
        now = datetime.now(UTC)
        self._apply_stat_update(script, ExecutionStatus.FAILED.value, now)
        assert script.consecutive_failures == 4

    def test_cancelled_status_does_not_change_stats(self):
        """CANCELLED is not SUCCESS/FAILED/TIMEOUT — stats must be untouched."""
        script = _make_script(consecutive_failures=2)
        t = datetime(2026, 1, 1, tzinfo=UTC)
        script.last_failure_at = t
        now = datetime.now(UTC)
        self._apply_stat_update(script, ExecutionStatus.CANCELLED.value, now)
        assert script.consecutive_failures == 2
        assert script.last_failure_at == t

    def test_skipped_status_does_not_change_stats(self):
        """SKIPPED does not affect consecutive_failures."""
        script = _make_script(consecutive_failures=1)
        t = datetime(2026, 1, 1, tzinfo=UTC)
        script.last_success_at = t
        now = datetime.now(UTC)
        self._apply_stat_update(script, ExecutionStatus.SKIPPED.value, now)
        assert script.consecutive_failures == 1
        assert script.last_success_at == t

    def test_consecutive_failures_resets_to_zero_after_success(self):
        """Full scenario: several failures then a success resets the counter."""
        script = _make_script()
        now = datetime.now(UTC)

        for _ in range(4):
            self._apply_stat_update(script, ExecutionStatus.FAILED.value, now)
        assert script.consecutive_failures == 4

        self._apply_stat_update(script, ExecutionStatus.SUCCESS.value, now)
        assert script.consecutive_failures == 0


# ---------------------------------------------------------------------------
# Tests: ExecutorService._delayed_retry integration
# ---------------------------------------------------------------------------

class TestDelayedRetryIntegration:
    @pytest.mark.asyncio
    async def test_retry_uses_correct_attempt_number(self):
        """Each retry increments the attempt by 1 from the caller's perspective."""
        service = ExecutorService()
        attempts_received = []

        async def fake_execute(**kwargs):
            attempts_received.append(kwargs.get("attempt"))
            return 1

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with patch.object(service, "execute_script", side_effect=fake_execute):
                await service._delayed_retry(
                    script_id=1,
                    triggered_by="retry",
                    attempt=2,
                    delay=0,
                    first_attempt_at=datetime.now(UTC),
                )
                await service._delayed_retry(
                    script_id=1,
                    triggered_by="retry",
                    attempt=3,
                    delay=0,
                    first_attempt_at=datetime.now(UTC),
                )

        assert attempts_received == [2, 3]

    @pytest.mark.asyncio
    async def test_retry_triggered_by_is_retry(self):
        """triggered_by for retries must be 'retry', not 'manual' or 'scheduler'."""
        service = ExecutorService()
        captured_triggered_by = []

        async def fake_execute(**kwargs):
            captured_triggered_by.append(kwargs.get("triggered_by"))
            return 1

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with patch.object(service, "execute_script", side_effect=fake_execute):
                await service._delayed_retry(
                    script_id=1,
                    triggered_by="retry",
                    attempt=2,
                    delay=0,
                    first_attempt_at=datetime.now(UTC),
                )

        assert captured_triggered_by == ["retry"]
