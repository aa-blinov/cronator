"""TDD tests for F3: Graceful Shutdown.

Tests the graceful_shutdown() function directly (it's a public function
extracted from the FastAPI lifespan handler so it can be tested in isolation).

On shutdown we must:
1. Stop the scheduler (no new jobs fire)
2. Cancel every in-flight execution (status=CANCELLED, not stuck RUNNING)
3. Close the database engine (release connections)
4. Be idempotent — safe to call twice
5. Tolerate partial failures (one step failing doesn't abort the rest)
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.main import graceful_shutdown


@pytest.mark.asyncio
async def test_graceful_shutdown_stops_scheduler():
    fake_scheduler = MagicMock()
    fake_scheduler.stop = AsyncMock()
    fake_executor = MagicMock()
    fake_executor.running_processes = {}
    fake_close_db = AsyncMock()

    await graceful_shutdown(fake_scheduler, fake_executor, fake_close_db)

    assert fake_scheduler.stop.called


@pytest.mark.asyncio
async def test_graceful_shutdown_cancels_in_flight_executions():
    fake_scheduler = MagicMock()
    fake_scheduler.stop = AsyncMock()
    fake_executor = MagicMock()
    fake_executor.running_processes = {1: MagicMock(), 2: MagicMock(), 3: MagicMock()}
    fake_close_db = AsyncMock()

    # Patch the singleton's cancel_execution so we can inspect calls
    from app.services.executor import executor_service as real_executor

    original_processes = real_executor.running_processes.copy()
    real_executor.running_processes = fake_executor.running_processes

    cancel_mock = AsyncMock()
    original_cancel = real_executor.cancel_execution
    real_executor.cancel_execution = cancel_mock
    try:
        await graceful_shutdown(fake_scheduler, fake_executor, fake_close_db)
        cancel_calls = cancel_mock.call_args_list
        assert len(cancel_calls) == 3, f"expected 3 cancel calls, got {len(cancel_calls)}"
        cancelled_ids = {c.args[0] for c in cancel_calls}
        assert cancelled_ids == {1, 2, 3}, cancelled_ids
    finally:
        real_executor.running_processes = original_processes
        real_executor.cancel_execution = original_cancel


@pytest.mark.asyncio
async def test_graceful_shutdown_no_in_flight_executions_is_noop():
    """If no executions are running, cancel_execution should not be called."""
    fake_scheduler = MagicMock()
    fake_scheduler.stop = AsyncMock()
    fake_executor = MagicMock()
    fake_executor.running_processes = {}
    fake_close_db = AsyncMock()

    from app.services.executor import executor_service as real_executor

    original_processes = real_executor.running_processes.copy()
    real_executor.running_processes = {}
    cancel_mock = AsyncMock()
    original_cancel = real_executor.cancel_execution
    real_executor.cancel_execution = cancel_mock
    try:
        await graceful_shutdown(fake_scheduler, fake_executor, fake_close_db)
        assert not cancel_mock.called
    finally:
        real_executor.running_processes = original_processes
        real_executor.cancel_execution = original_cancel


@pytest.mark.asyncio
async def test_graceful_shutdown_closes_database():
    fake_scheduler = MagicMock()
    fake_scheduler.stop = AsyncMock()
    fake_executor = MagicMock()
    fake_executor.running_processes = {}
    fake_close_db = AsyncMock()

    await graceful_shutdown(fake_scheduler, fake_executor, fake_close_db)

    assert fake_close_db.called


@pytest.mark.asyncio
async def test_graceful_shutdown_is_idempotent():
    """Calling twice must not raise — each step is idempotent."""
    fake_scheduler = MagicMock()
    fake_scheduler.stop = AsyncMock()
    fake_executor = MagicMock()
    fake_executor.running_processes = {}
    fake_close_db = AsyncMock()

    await graceful_shutdown(fake_scheduler, fake_executor, fake_close_db)
    # Second call should be safe
    await graceful_shutdown(fake_scheduler, fake_executor, fake_close_db)
    assert fake_scheduler.stop.call_count == 2
    assert fake_close_db.call_count == 2


@pytest.mark.asyncio
async def test_graceful_shutdown_tolerates_scheduler_failure():
    """If scheduler.stop() raises, we still try to cancel executions and close DB."""
    fake_scheduler = MagicMock()
    fake_scheduler.stop = AsyncMock(side_effect=RuntimeError("scheduler boom"))
    fake_executor = MagicMock()
    fake_executor.running_processes = {}
    fake_close_db = AsyncMock()

    # Should not raise
    await graceful_shutdown(fake_scheduler, fake_executor, fake_close_db)
    assert fake_close_db.called, "close_db should still be called even after scheduler failure"


@pytest.mark.asyncio
async def test_graceful_shutdown_tolerates_db_close_failure():
    """If close_db() raises, we don't propagate (we're already shutting down)."""
    fake_scheduler = MagicMock()
    fake_scheduler.stop = AsyncMock()
    fake_executor = MagicMock()
    fake_executor.running_processes = {}
    fake_close_db = AsyncMock(side_effect=RuntimeError("db boom"))

    # Should not raise
    await graceful_shutdown(fake_scheduler, fake_executor, fake_close_db)
