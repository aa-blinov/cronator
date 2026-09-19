"""Regression coverage for ExecutorService._run_script's outer except
handler — real database, no subprocess.

If something inside the main try body raises before a normal
_finish_execution() call (e.g. the env-setup check), the handler retries
_finish_execution() to mark the execution FAILED. If THAT retry also
raises (classic case: the first failure was itself a commit, leaving the
session needing a rollback before reuse), close_stream() must still run
— otherwise any SSE client following the execution is left waiting on a
stream that will never send a "done" event, since cleanup_stale_executions
only runs once at app startup.
"""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import Execution, ExecutionStatus
from app.models.script import Script
from app.services.executor import ExecutorService

pytestmark = pytest.mark.asyncio


async def _running_execution(db_session: AsyncSession, script: Script) -> Execution:
    execution = Execution(script_id=script.id, status=ExecutionStatus.RUNNING.value)
    db_session.add(execution)
    await db_session.commit()
    await db_session.refresh(execution)
    return execution


class TestRunScriptOuterExceptRecovery:
    async def test_close_stream_runs_even_when_finish_execution_retry_fails(
        self,
        exec_service: ExecutorService,
        db_script: Script,
        db_session: AsyncSession,
        tmp_path,
    ):
        execution = await _running_execution(db_session, db_script)

        script_file = tmp_path / "main.py"
        script_file.write_text("print('hi')\n")

        with (
            patch.object(exec_service, "_get_script_path", return_value=script_file),
            patch(
                "app.services.executor.environment_service.env_exists",
                new=AsyncMock(side_effect=RuntimeError("db gone")),
            ),
            patch.object(
                exec_service,
                "_finish_execution",
                new=AsyncMock(side_effect=RuntimeError("still broken")),
            ),
            patch.object(exec_service, "close_stream", new=AsyncMock()) as mock_close_stream,
        ):
            # Must not raise: an unrecorded failure to mark FAILED should
            # never escape as an unhandled exception from a fire-and-forget
            # background task.
            await exec_service._run_script(db_script.id, execution.id)

        mock_close_stream.assert_awaited_once_with(execution.id)

    async def test_session_is_rolled_back_before_retrying_finish_execution(
        self,
        exec_service: ExecutorService,
        db_script: Script,
        db_session: AsyncSession,
        test_engine,
        tmp_path,
    ):
        """The retry path must roll back the session first — otherwise a
        session left dirty by a failed commit raises again on the very
        first query _finish_execution makes (db.refresh)."""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        execution = await _running_execution(db_session, db_script)

        script_file = tmp_path / "main.py"
        script_file.write_text("print('hi')\n")

        with (
            patch.object(exec_service, "_get_script_path", return_value=script_file),
            patch(
                "app.services.executor.environment_service.env_exists",
                new=AsyncMock(side_effect=RuntimeError("boom")),
            ),
            patch.object(exec_service, "close_stream", new=AsyncMock()),
        ):
            await exec_service._run_script(db_script.id, execution.id)

        verify_session = async_sessionmaker(test_engine, class_=AsyncSession)()
        async with verify_session as verify:
            refreshed = await verify.get(Execution, execution.id)
            assert refreshed.status == ExecutionStatus.FAILED.value
            assert refreshed.error_message == "boom"
