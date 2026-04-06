"""
Integration tests for ExecutorService concurrency — real database, no subprocess.

Verifies:
  - that an Execution record is created in the DB when a script is started
  - that a second call for the same script creates a SKIPPED execution (prevent_overlap=True)
  - that different scripts can run in parallel without conflict
  - that after completion a script can be re-run (new DB record created)
  - that the initial Execution status is RUNNING
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import Execution, ExecutionStatus
from app.models.script import Script
from app.services.executor import ExecutorService

# ─────────────────────────── tests ───────────────────────────────────────────


class TestConcurrencyIntegration:
    """Integration tests for duplicate-run prevention."""

    @pytest.mark.asyncio
    async def test_execute_script_creates_execution_in_db(
        self,
        exec_service: ExecutorService,
        db_script: Script,
        db_session: AsyncSession,
    ):
        """execute_script() creates an Execution record in the DB with the correct script_id."""
        script_id = db_script.id  # save before potential expire
        with patch.object(exec_service, "_run_script", new=AsyncMock()):
            eid = await exec_service.execute_script(script_id)

        assert eid is not None
        # rollback ends the current transaction → new one sees the exec_service commit
        await db_session.rollback()
        execution = await db_session.get(Execution, eid)
        assert execution is not None
        assert execution.script_id == script_id

    @pytest.mark.asyncio
    async def test_execution_status_is_running_initially(
        self,
        exec_service: ExecutorService,
        db_script: Script,
        db_session: AsyncSession,
    ):
        """Immediately after launch, the Execution status is RUNNING."""
        script_id = db_script.id
        with patch.object(exec_service, "_run_script", new=AsyncMock()):
            eid = await exec_service.execute_script(script_id)

        await db_session.rollback()
        execution = await db_session.get(Execution, eid)
        assert execution.status == ExecutionStatus.RUNNING.value

    @pytest.mark.asyncio
    async def test_second_call_same_script_creates_skipped_execution(
        self,
        exec_service: ExecutorService,
        db_script: Script,
        db_session: AsyncSession,
    ):
        """A second execute_script call for a running script (prevent_overlap=True) creates a SKIPPED execution."""
        script_id = db_script.id
        with patch.object(exec_service, "_run_script", new=AsyncMock()):
            await exec_service.execute_script(script_id)

        skipped_id = await exec_service.execute_script(script_id)
        assert skipped_id is not None

        await db_session.rollback()
        skipped_exec = await db_session.get(Execution, skipped_id)
        assert skipped_exec is not None
        assert skipped_exec.status == ExecutionStatus.SKIPPED.value

    @pytest.mark.asyncio
    async def test_concurrent_different_scripts_both_succeed(
        self,
        exec_service: ExecutorService,
        db_session: AsyncSession,
    ):
        """Two different scripts launched in parallel both get Execution records in the DB."""
        script_a = Script(
            name="conc_int_a",
            content="print('a')",
            cron_expression="0 * * * *",
            enabled=True,
            python_version="3.12",
            timeout=3600,
            path="/scripts/conc_int_a/main.py",
        )
        script_b = Script(
            name="conc_int_b",
            content="print('b')",
            cron_expression="0 * * * *",
            enabled=True,
            python_version="3.12",
            timeout=3600,
            path="/scripts/conc_int_b/main.py",
        )
        db_session.add_all([script_a, script_b])
        await db_session.commit()
        await db_session.refresh(script_a)
        await db_session.refresh(script_b)

        sid_a, sid_b = script_a.id, script_b.id  # save before expire

        with patch.object(exec_service, "_run_script", new=AsyncMock()):
            id_a, id_b = await asyncio.gather(
                exec_service.execute_script(sid_a),
                exec_service.execute_script(sid_b),
            )

        assert id_a is not None
        assert id_b is not None
        assert id_a != id_b

        await db_session.rollback()
        exec_a = await db_session.get(Execution, id_a)
        exec_b = await db_session.get(Execution, id_b)
        assert exec_a.script_id == sid_a
        assert exec_b.script_id == sid_b

    @pytest.mark.asyncio
    async def test_script_can_rerun_after_completion(
        self,
        exec_service: ExecutorService,
        db_script: Script,
        db_session: AsyncSession,
    ):
        """After removal from _running_scripts, the script can be re-run, creating a new Execution."""
        script_id = db_script.id

        with patch.object(exec_service, "_run_script", new=AsyncMock()):
            eid1 = await exec_service.execute_script(script_id)

        exec_service._running_scripts.discard(script_id)

        with patch.object(exec_service, "_run_script", new=AsyncMock()):
            eid2 = await exec_service.execute_script(script_id)

        assert eid1 != eid2

        await db_session.rollback()
        result = await db_session.execute(
            select(Execution).where(Execution.script_id == script_id)
        )
        executions = result.scalars().all()
        assert len(executions) == 2

    @pytest.mark.asyncio
    async def test_script_not_found_raises_and_cleans_running_set(
        self,
        exec_service: ExecutorService,
    ):
        """If the script is not found in the DB, an exception is raised and script_id is removed from _running_scripts."""
        non_existent_id = 99999

        with pytest.raises(ValueError, match="not found"):
            await exec_service.execute_script(non_existent_id)

        # After the error, the script must not remain stuck as "running"
        assert not exec_service.is_script_running(non_existent_id)
