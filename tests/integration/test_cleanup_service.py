"""cleanup_service.py had 0% test coverage before this file. Two real bugs
were found while writing these tests:

1. RETENTION_BY_STATUS never included ExecutionStatus.TIMEOUT — the daily
   cleanup_by_status() job iterates only the statuses in that dict, so
   timed-out executions were never touched no matter how many piled up.
2. cleanup_service wasn't in conftest.py's async_session_maker patch list
   (it does `from app.database import async_session_maker`, a by-name
   import that isn't affected by patching app.database's attribute), so
   calling it through test_client would have silently hit the real
   dev/prod database instead of the test one — nothing ever caught this
   because nothing ever exercised the cleanup endpoints in tests.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.config import get_settings
from app.models.execution import ExecutionStatus
from app.services.cleanup_service import RETENTION_BY_STATUS, cleanup_service


@pytest.fixture
def artifacts_dir(tmp_path, monkeypatch):
    """Point settings.artifacts_dir at an isolated tmp dir for this test."""
    settings = get_settings()
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path)
    return tmp_path


def _make_artifact_dir(base: Path, execution_id: int) -> None:
    d = base / str(execution_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "output.csv").write_text("data")


class TestCleanupByStatus:
    @pytest.mark.asyncio
    async def test_keeps_only_the_most_recent_n_per_status(
        self, test_client, script_factory, execution_factory, monkeypatch
    ):
        monkeypatch.setitem(RETENTION_BY_STATUS, ExecutionStatus.SUCCESS.value, 2)
        script = await script_factory(name="cleanup_status_test")

        now = datetime.now(UTC)
        executions = []
        for i in range(5):
            executions.append(
                await execution_factory(
                    script_id=script.id,
                    status=ExecutionStatus.SUCCESS.value,
                    started_at=now - timedelta(minutes=i),
                )
            )

        result = await cleanup_service.cleanup_by_status()

        assert result["deleted_executions"] == 3

        # Verify directly against the DB: only the 2 most recent survive.
        from sqlalchemy import select

        from app.database import async_session_maker
        from app.models.execution import Execution

        async with async_session_maker() as db:
            rows = await db.execute(
                select(Execution.id).where(Execution.script_id == script.id)
            )
            remaining_ids = {r[0] for r in rows.all()}

        assert remaining_ids == {executions[0].id, executions[1].id}

    @pytest.mark.asyncio
    async def test_removes_artifact_dirs_for_deleted_executions_only(
        self, test_client, script_factory, execution_factory, monkeypatch, artifacts_dir
    ):
        monkeypatch.setitem(RETENTION_BY_STATUS, ExecutionStatus.SUCCESS.value, 1)
        script = await script_factory(name="cleanup_artifact_test")

        now = datetime.now(UTC)
        kept = await execution_factory(
            script_id=script.id, status=ExecutionStatus.SUCCESS.value, started_at=now
        )
        deleted = await execution_factory(
            script_id=script.id,
            status=ExecutionStatus.SUCCESS.value,
            started_at=now - timedelta(minutes=5),
        )
        _make_artifact_dir(artifacts_dir, kept.id)
        _make_artifact_dir(artifacts_dir, deleted.id)

        result = await cleanup_service.cleanup_by_status()

        assert result["deleted_artifact_dirs"] == 1
        assert (artifacts_dir / str(kept.id)).exists()
        assert not (artifacts_dir / str(deleted.id)).exists()

    @pytest.mark.asyncio
    async def test_never_touches_running_executions(
        self, test_client, script_factory, execution_factory
    ):
        """RUNNING isn't in RETENTION_BY_STATUS at all — the daily job must
        never delete an execution that's still in progress, regardless of
        how many there are."""
        script = await script_factory(name="cleanup_running_test")
        now = datetime.now(UTC)
        for i in range(10):
            await execution_factory(
                script_id=script.id,
                status=ExecutionStatus.RUNNING.value,
                started_at=now - timedelta(minutes=i),
            )

        result = await cleanup_service.cleanup_by_status()

        from sqlalchemy import func, select

        from app.database import async_session_maker
        from app.models.execution import Execution

        async with async_session_maker() as db:
            count = await db.scalar(
                select(func.count(Execution.id)).where(Execution.script_id == script.id)
            )
        assert count == 10
        assert result["deleted_executions"] == 0

    @pytest.mark.asyncio
    async def test_cleans_up_timed_out_executions(
        self, test_client, script_factory, execution_factory, monkeypatch
    ):
        """Regression test for the missing-TIMEOUT-in-RETENTION_BY_STATUS bug:
        before the fix, this assertion would fail because TIMEOUT executions
        were never queried by cleanup_by_status() at all."""
        assert ExecutionStatus.TIMEOUT.value in RETENTION_BY_STATUS, (
            "TIMEOUT must be covered by the daily cleanup job — otherwise "
            "timed-out executions accumulate in the DB forever"
        )
        monkeypatch.setitem(RETENTION_BY_STATUS, ExecutionStatus.TIMEOUT.value, 2)
        script = await script_factory(name="cleanup_timeout_test")

        now = datetime.now(UTC)
        for i in range(5):
            await execution_factory(
                script_id=script.id,
                status=ExecutionStatus.TIMEOUT.value,
                started_at=now - timedelta(minutes=i),
            )

        result = await cleanup_service.cleanup_by_status()

        assert result["deleted_executions"] == 3

    @pytest.mark.asyncio
    async def test_is_scoped_per_script(
        self, test_client, script_factory, execution_factory, monkeypatch
    ):
        """Retention is per script — a script with few runs must not have
        its executions deleted just because another script has many."""
        monkeypatch.setitem(RETENTION_BY_STATUS, ExecutionStatus.SUCCESS.value, 1)
        busy_script = await script_factory(name="busy_script")
        quiet_script = await script_factory(name="quiet_script")

        now = datetime.now(UTC)
        for i in range(5):
            await execution_factory(
                script_id=busy_script.id,
                status=ExecutionStatus.SUCCESS.value,
                started_at=now - timedelta(minutes=i),
            )
        quiet_exec = await execution_factory(
            script_id=quiet_script.id, status=ExecutionStatus.SUCCESS.value, started_at=now
        )

        await cleanup_service.cleanup_by_status()

        from sqlalchemy import select

        from app.database import async_session_maker
        from app.models.execution import Execution

        async with async_session_maker() as db:
            rows = await db.execute(
                select(Execution.id).where(Execution.script_id == quiet_script.id)
            )
            assert {r[0] for r in rows.all()} == {quiet_exec.id}


class TestCleanupOlderThanDays:
    @pytest.mark.asyncio
    async def test_deletes_only_non_running_executions_past_the_cutoff(
        self, test_client, script_factory, execution_factory
    ):
        script = await script_factory(name="age_cleanup_test")
        now = datetime.now(UTC)

        old_success = await execution_factory(
            script_id=script.id,
            status=ExecutionStatus.SUCCESS.value,
            started_at=now - timedelta(days=100),
        )
        old_running = await execution_factory(
            script_id=script.id,
            status=ExecutionStatus.RUNNING.value,
            started_at=now - timedelta(days=100),
        )
        recent_success = await execution_factory(
            script_id=script.id, status=ExecutionStatus.SUCCESS.value, started_at=now
        )

        result = await cleanup_service.cleanup_older_than_days(90)

        assert result["deleted_executions"] == 1

        from sqlalchemy import select

        from app.database import async_session_maker
        from app.models.execution import Execution

        async with async_session_maker() as db:
            rows = await db.execute(
                select(Execution.id).where(Execution.script_id == script.id)
            )
            remaining = {r[0] for r in rows.all()}

        assert remaining == {old_running.id, recent_success.id}
        assert old_success.id not in remaining

    @pytest.mark.asyncio
    async def test_removes_artifact_dirs_for_deleted_executions(
        self, test_client, script_factory, execution_factory, artifacts_dir
    ):
        script = await script_factory(name="age_cleanup_artifacts_test")
        now = datetime.now(UTC)
        old = await execution_factory(
            script_id=script.id,
            status=ExecutionStatus.SUCCESS.value,
            started_at=now - timedelta(days=100),
        )
        _make_artifact_dir(artifacts_dir, old.id)

        result = await cleanup_service.cleanup_older_than_days(90)

        assert result["deleted_artifact_dirs"] == 1
        assert not (artifacts_dir / str(old.id)).exists()

    @pytest.mark.asyncio
    async def test_returns_zero_when_nothing_is_old_enough(
        self, test_client, script_factory, execution_factory
    ):
        script = await script_factory(name="age_cleanup_noop_test")
        await execution_factory(
            script_id=script.id,
            status=ExecutionStatus.SUCCESS.value,
            started_at=datetime.now(UTC),
        )

        result = await cleanup_service.cleanup_older_than_days(90)

        assert result == {"deleted_executions": 0, "deleted_artifact_dirs": 0}


class TestGetExecutionStats:
    @pytest.mark.asyncio
    async def test_counts_by_status_and_finds_oldest(
        self, test_client, script_factory, execution_factory
    ):
        script = await script_factory(name="stats_test")
        now = datetime.now(UTC)
        oldest = now - timedelta(days=10)

        await execution_factory(
            script_id=script.id, status=ExecutionStatus.SUCCESS.value, started_at=oldest
        )
        await execution_factory(
            script_id=script.id, status=ExecutionStatus.SUCCESS.value, started_at=now
        )
        await execution_factory(
            script_id=script.id, status=ExecutionStatus.FAILED.value, started_at=now
        )
        # RUNNING executions are excluded from the "oldest" calculation —
        # an in-progress run shouldn't be reported as the oldest record.
        await execution_factory(
            script_id=script.id,
            status=ExecutionStatus.RUNNING.value,
            started_at=now - timedelta(days=365),
        )

        stats = await cleanup_service.get_execution_stats()

        assert stats["total"] == 4
        assert stats["by_status"][ExecutionStatus.SUCCESS.value] == 2
        assert stats["by_status"][ExecutionStatus.FAILED.value] == 1
        assert stats["by_status"][ExecutionStatus.RUNNING.value] == 1
        assert stats["oldest_at"] is not None
        assert stats["oldest_at"].startswith(oldest.date().isoformat())

    @pytest.mark.asyncio
    async def test_oldest_is_none_when_no_executions_exist(self, test_client):
        stats = await cleanup_service.get_execution_stats()
        assert stats["total"] == 0
        assert stats["oldest_at"] is None


class TestCleanupEndpointsUseTheTestDatabase:
    """Regression coverage for the conftest.py patching gap: cleanup_service
    imports async_session_maker by name, so patching app.database's
    attribute alone doesn't reach it. If this patch ever regresses, these
    calls would hit the real dev/prod DB file instead of the test one — a
    silent, hard-to-notice failure mode rather than a loud test failure.
    """

    @pytest.mark.asyncio
    async def test_execution_stats_endpoint_reflects_test_db(
        self, test_client, script_factory, execution_factory
    ):
        script = await script_factory(name="endpoint_stats_test")
        await execution_factory(script_id=script.id, status=ExecutionStatus.SUCCESS.value)

        response = await test_client.get("/api/settings/execution-stats")

        assert response.status_code == 200
        assert response.json()["total"] == 1

    @pytest.mark.asyncio
    async def test_cleanup_executions_endpoint_operates_on_the_test_db(
        self, test_client, script_factory, execution_factory
    ):
        script = await script_factory(name="endpoint_cleanup_test")
        await execution_factory(
            script_id=script.id,
            status=ExecutionStatus.SUCCESS.value,
            started_at=datetime.now(UTC) - timedelta(days=200),
        )

        response = await test_client.post(
            "/api/settings/cleanup-executions", json={"days": 90}
        )

        assert response.status_code == 200
        assert response.json()["deleted_executions"] == 1
