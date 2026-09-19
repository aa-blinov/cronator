"""Unit tests for database models."""

import pytest

from app.models.execution import Execution, ExecutionStatus
from app.models.script import Script


class TestExecutionStatus:
    """Tests for ExecutionStatus enum."""

    def test_status_values(self):
        """Test that all status values are strings."""
        assert ExecutionStatus.PENDING.value == "pending"
        assert ExecutionStatus.RUNNING.value == "running"
        assert ExecutionStatus.SUCCESS.value == "success"
        assert ExecutionStatus.FAILED.value == "failed"
        assert ExecutionStatus.TIMEOUT.value == "timeout"
        assert ExecutionStatus.CANCELLED.value == "cancelled"

    def test_status_is_string_enum(self):
        """Test that ExecutionStatus inherits from str."""
        assert isinstance(ExecutionStatus.SUCCESS, str)
        assert ExecutionStatus.SUCCESS == "success"


class TestScript:
    """Tests for Script model."""

    @pytest.mark.asyncio
    async def test_create_script(self, db_session):
        """Test creating a script."""
        script = Script(
            name="test_script",
            path="/scripts/test/main.py",
            content="print('hello')",
            cron_expression="*/5 * * * *",
        )
        db_session.add(script)
        await db_session.commit()
        await db_session.refresh(script)

        assert script.id is not None
        assert script.name == "test_script"
        assert script.enabled is True  # default
        assert script.python_version == "3.12"  # default
        assert script.timeout == 3600  # default

    @pytest.mark.asyncio
    async def test_script_repr(self, script_factory):
        """Test script string representation."""
        script = await script_factory(name="repr_test")
        repr_str = repr(script)
        assert "Script" in repr_str
        assert "repr_test" in repr_str


class TestExecution:
    """Tests for Execution model."""

    @pytest.mark.asyncio
    async def test_create_execution(self, script_factory, db_session):
        """Test creating an execution."""
        script = await script_factory(name="exec_test_script")

        execution = Execution(
            script_id=script.id,
            status=ExecutionStatus.RUNNING.value,
            triggered_by="manual",
        )
        db_session.add(execution)
        await db_session.commit()
        await db_session.refresh(execution)

        assert execution.id is not None
        assert execution.script_id == script.id
        assert execution.status == "running"
        assert execution.is_test is False  # default

    @pytest.mark.asyncio
    async def test_is_finished_success(self, execution_factory, sample_script):
        """Test is_finished for successful execution."""
        execution = await execution_factory(
            script_id=sample_script.id,
            status=ExecutionStatus.SUCCESS.value,
        )
        assert execution.is_finished is True

    @pytest.mark.asyncio
    async def test_is_finished_running(self, execution_factory, sample_script):
        """Test is_finished for running execution."""
        execution = await execution_factory(
            script_id=sample_script.id,
            status=ExecutionStatus.RUNNING.value,
        )
        assert execution.is_finished is False

    @pytest.mark.asyncio
    async def test_is_finished_all_terminal_states(self, execution_factory, sample_script):
        """Test is_finished for all terminal states."""
        terminal_statuses = [
            ExecutionStatus.SUCCESS,
            ExecutionStatus.FAILED,
            ExecutionStatus.TIMEOUT,
            ExecutionStatus.CANCELLED,
        ]
        for status in terminal_statuses:
            execution = await execution_factory(
                script_id=sample_script.id,
                status=status.value,
            )
            assert execution.is_finished is True, f"Status {status} should be finished"

    @pytest.mark.asyncio
    async def test_duration_formatted_seconds(self, execution_factory, sample_script):
        """Test duration formatting for seconds."""
        execution = await execution_factory(
            script_id=sample_script.id,
            duration_ms=5500,  # 5.5 seconds
        )
        assert execution.duration_formatted == "5.5s"

    @pytest.mark.asyncio
    async def test_duration_formatted_minutes(self, execution_factory, sample_script):
        """Test duration formatting for minutes."""
        execution = await execution_factory(
            script_id=sample_script.id,
            duration_ms=150000,  # 2.5 minutes
        )
        assert execution.duration_formatted == "2.5m"

    @pytest.mark.asyncio
    async def test_duration_formatted_hours(self, execution_factory, sample_script):
        """Test duration formatting for hours."""
        execution = await execution_factory(
            script_id=sample_script.id,
            duration_ms=5400000,  # 1.5 hours
        )
        assert execution.duration_formatted == "1.5h"

    @pytest.mark.asyncio
    async def test_duration_formatted_none(self, execution_factory, sample_script):
        """Test duration formatting when duration is None."""
        execution = await execution_factory(
            script_id=sample_script.id,
            duration_ms=None,
        )
        assert execution.duration_formatted == "-"

    @pytest.mark.asyncio
    async def test_execution_repr(self, execution_factory, sample_script):
        """Test execution string representation."""
        execution = await execution_factory(script_id=sample_script.id)
        repr_str = repr(execution)
        assert "Execution" in repr_str
        assert str(sample_script.id) in repr_str
