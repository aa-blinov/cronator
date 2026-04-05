"""Unit tests for ExecutorService concurrency control (per-script lock, _running_scripts)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.executor import ExecutorService

# ─────────────────────────── helpers ─────────────────────────────────────────


def _make_session_maker(execution_id: int = 99, script_id: int = 1):
    """
    Mock async_session_maker: returns a script from execute(),
    and sets execution.id = execution_id after db.refresh().
    """
    script = MagicMock()
    script.id = script_id

    script_result = MagicMock()
    script_result.scalar_one_or_none.return_value = script

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=script_result)
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()

    async def mock_refresh(obj):
        obj.id = execution_id

    mock_db.refresh = mock_refresh

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_db)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return MagicMock(return_value=ctx)


def _discard_background_task(coro):
    """Close fire-and-forget coroutines instead of leaking them during tests."""
    if hasattr(coro, "close"):
        coro.close()
    return MagicMock()


# ─────────────────────────── per-script lock ─────────────────────────────────


class TestScriptLock:
    """Tests for _get_script_lock."""

    def test_same_lock_returned_for_same_script(self):
        """The same asyncio.Lock is returned for the same script_id."""
        service = ExecutorService()
        lock_a = service._get_script_lock(1)
        lock_b = service._get_script_lock(1)
        assert lock_a is lock_b

    def test_different_locks_for_different_scripts(self):
        """Different script_ids get independent locks."""
        service = ExecutorService()
        assert service._get_script_lock(1) is not service._get_script_lock(2)

# ─────────────────────────── _running_scripts ────────────────────────────────


class TestRunningScripts:
    """Tests for protection against concurrent execution of the same script."""

    @pytest.mark.asyncio
    async def test_raises_if_script_already_marked_running(self):
        """If script_id is already in _running_scripts, raises ValueError without hitting the DB."""
        service = ExecutorService()
        service._running_scripts.add(1)

        with pytest.raises(ValueError, match="already running"):
            await service.execute_script(1)

    @pytest.mark.asyncio
    async def test_second_concurrent_call_raises(self):
        """Two execute_script calls for the same script: the second raises ValueError."""
        service = ExecutorService()

        with (
            patch("app.services.executor.async_session_maker", _make_session_maker(99)),
            patch(
                "app.services.executor.asyncio.create_task",
                side_effect=_discard_background_task,
            ),
        ):
            exec_id = await service.execute_script(1)
            assert exec_id == 99

            # script_id=1 is still in _running_scripts
            with pytest.raises(ValueError, match="already running"):
                await service.execute_script(1)

    @pytest.mark.asyncio
    async def test_different_scripts_run_concurrently(self):
        """Different script_ids can run in parallel without conflict."""
        service = ExecutorService()

        call_count = 0

        def session_maker():
            nonlocal call_count
            call_count += 1
            exec_id = 10 if call_count == 1 else 20
            return _make_session_maker(exec_id)()

        with (
            patch("app.services.executor.async_session_maker", session_maker),
            patch(
                "app.services.executor.asyncio.create_task",
                side_effect=_discard_background_task,
            ),
        ):
            id1, id2 = await asyncio.gather(
                service.execute_script(1),
                service.execute_script(2),
            )

        assert id1 == 10
        assert id2 == 20
        # both scripts are tracked as running
        assert 1 in service._running_scripts
        assert 2 in service._running_scripts

    @pytest.mark.asyncio
    async def test_script_can_rerun_after_completion(self):
        """After removal from _running_scripts, the same script can be executed again."""
        service = ExecutorService()

        with (
            patch("app.services.executor.async_session_maker", _make_session_maker(42)),
            patch(
                "app.services.executor.asyncio.create_task",
                side_effect=_discard_background_task,
            ),
        ):
            eid = await service.execute_script(1)
            assert eid == 42

        # Simulate _run_script completing
        service._running_scripts.discard(1)

        with (
            patch("app.services.executor.async_session_maker", _make_session_maker(43)),
            patch(
                "app.services.executor.asyncio.create_task",
                side_effect=_discard_background_task,
            ),
        ):
            eid2 = await service.execute_script(1)
            assert eid2 == 43

    @pytest.mark.asyncio
    async def test_is_script_running_true_while_executing(self):
        """is_script_running() returns True while the script is tracked as running."""
        service = ExecutorService()

        with (
            patch("app.services.executor.async_session_maker", _make_session_maker(99)),
            patch(
                "app.services.executor.asyncio.create_task",
                side_effect=_discard_background_task,
            ),
        ):
            await service.execute_script(1)

        assert service.is_script_running(1) is True

    @pytest.mark.asyncio
    async def test_script_added_to_running_before_db_call(self):
        """
        script_id is added to _running_scripts before the first DB call,
        preventing any race condition.
        """
        service = ExecutorService()
        added_before_db: list[bool] = []

        def sync_check_and_get_db():
            """Synchronous wrapper — returns an async context manager, like the real session_maker."""
            added_before_db.append(1 in service._running_scripts)

            script_result = MagicMock()
            script_result.scalar_one_or_none.return_value = None  # Script not found

            mock_db = AsyncMock()
            mock_db.execute = AsyncMock(return_value=script_result)

            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=mock_db)
            ctx.__aexit__ = AsyncMock(return_value=None)
            return ctx

        with patch("app.services.executor.async_session_maker", sync_check_and_get_db):
            try:
                await service.execute_script(1)
            except ValueError:
                pass  # Script not found — expected

        assert added_before_db == [True], (
            "script_id must be in _running_scripts BEFORE the first DB call"
        )
