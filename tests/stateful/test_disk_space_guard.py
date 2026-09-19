"""min_free_space_mb existed in settings and was shown in /api/diagnostics
but nothing ever enforced it — a script filling the disk had no backstop
at all. execute_script() now refuses to start a new run when free space
is below the configured minimum, real database, no subprocess.
"""

from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import ExecutionStatus
from app.models.script import Script
from app.services.executor import ExecutorService

pytestmark = pytest.mark.asyncio


class TestDiskSpaceGuard:
    async def test_refuses_to_start_when_disk_is_low(
        self,
        exec_service: ExecutorService,
        db_script: Script,
        test_engine,
    ):
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.models.execution import Execution

        with patch.object(exec_service, "_get_free_space_mb", return_value=5):
            execution_id = await exec_service.execute_script(db_script.id, triggered_by="manual")

        verify_session = async_sessionmaker(test_engine, class_=AsyncSession)()
        async with verify_session as verify:
            execution = await verify.get(Execution, execution_id)
            assert execution.status == ExecutionStatus.FAILED.value
            assert "disk space" in execution.error_message.lower()
        # The lock/running-set bookkeeping is only touched past the disk
        # check — a refused run must not leave the script stuck "running".
        assert not exec_service.is_script_running(db_script.id)

    async def test_runs_normally_when_disk_is_fine(
        self,
        exec_service: ExecutorService,
        db_script: Script,
        test_engine,
    ):
        from unittest.mock import AsyncMock

        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.models.execution import Execution

        with (
            patch.object(exec_service, "_get_free_space_mb", return_value=100_000),
            patch.object(exec_service, "_run_script", new=AsyncMock()),
        ):
            execution_id = await exec_service.execute_script(db_script.id, triggered_by="manual")

        verify_session = async_sessionmaker(test_engine, class_=AsyncSession)()
        async with verify_session as verify:
            execution = await verify.get(Execution, execution_id)
            assert execution.status == ExecutionStatus.RUNNING.value

    async def test_unknown_free_space_never_blocks_execution(
        self,
        exec_service: ExecutorService,
        db_script: Script,
        test_engine,
    ):
        """_get_free_space_mb returning None (can't stat the volume) must
        fail open, not closed — an unrelated filesystem hiccup shouldn't
        stop every script from ever running again."""
        from unittest.mock import AsyncMock

        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.models.execution import Execution

        with (
            patch.object(exec_service, "_get_free_space_mb", return_value=None),
            patch.object(exec_service, "_run_script", new=AsyncMock()),
        ):
            execution_id = await exec_service.execute_script(db_script.id, triggered_by="manual")

        verify_session = async_sessionmaker(test_engine, class_=AsyncSession)()
        async with verify_session as verify:
            execution = await verify.get(Execution, execution_id)
            assert execution.status == ExecutionStatus.RUNNING.value
