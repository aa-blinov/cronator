"""Unit tests for Executor service."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.execution import ExecutionStatus
from app.services.executor import ExecutorService


class TestExecutorService:
    """Tests for ExecutorService."""

    def test_init(self):
        """Test ExecutorService initialization."""
        service = ExecutorService()
        assert service.running_processes == {}
        assert service.output_queues == {}

    def test_is_script_running_false(self):
        """Test is_script_running when not running."""
        service = ExecutorService()
        assert service.is_script_running(1) is False

    def test_is_script_running_true(self):
        """Test is_script_running when running."""
        service = ExecutorService()
        # The actual implementation uses _running_scripts set
        service._running_scripts.add(1)
        assert service.is_script_running(1) is True

    def test_get_script_lock_creates_new(self):
        """Test that _get_script_lock creates new lock."""
        service = ExecutorService()
        lock1 = service._get_script_lock(1)
        assert isinstance(lock1, asyncio.Lock)

    def test_get_script_lock_returns_same(self):
        """Test that _get_script_lock returns same lock for same script."""
        service = ExecutorService()
        lock1 = service._get_script_lock(1)
        lock2 = service._get_script_lock(1)
        assert lock1 is lock2

    def test_get_script_lock_different_scripts(self):
        """Test that different scripts get different locks."""
        service = ExecutorService()
        lock1 = service._get_script_lock(1)
        lock2 = service._get_script_lock(2)
        assert lock1 is not lock2

    @pytest.mark.asyncio
    async def test_cancel_execution_not_running(self):
        """Test canceling execution that's not running."""
        service = ExecutorService()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("app.services.executor.async_session_maker", return_value=mock_session_ctx):
            result = await service.cancel_execution(999)
            assert result is False

    @pytest.mark.asyncio
    async def test_cancel_execution_running(self):
        """Test canceling a running execution."""
        service = ExecutorService()

        # Create mock process - cancel uses execution_id as key and kill()
        mock_process = MagicMock()
        mock_process.kill = MagicMock()
        mock_process.returncode = None

        execution_id = 1
        service.running_processes[execution_id] = mock_process

        # Create a proper async context manager mock
        mock_execution = MagicMock()
        mock_execution.status = ExecutionStatus.RUNNING.value

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_execution)

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("app.services.executor.async_session_maker", return_value=mock_session_ctx):
            result = await service.cancel_execution(execution_id)
            assert result is True
            mock_process.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_stale_executions(self):
        """Test cleanup of stale executions runs without error."""
        service = ExecutorService()

        # Create proper mock for scalars().all()
        mock_scalars = MagicMock()
        mock_scalars.all = MagicMock(return_value=[])

        mock_result = MagicMock()
        mock_result.scalars = MagicMock(return_value=mock_scalars)

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("app.services.executor.async_session_maker", return_value=mock_session_ctx):
            # Should not raise
            await service.cleanup_stale_executions()


class TestExecutorServiceScriptPath:
    """Tests for script path handling in ExecutorService."""

    @pytest.mark.asyncio
    async def test_get_script_path_with_content(self, script_factory):
        """Test getting path for script with content."""
        script = await script_factory(
            name="path_test",
            content="print('test')",
            path="/scripts/path_test/main.py",
        )

        service = ExecutorService()
        path = service._get_script_path(script)

        assert path is not None
        assert "path_test" in str(path)
