"""Coverage for app/api/executions.py endpoints not exercised elsewhere:
cancel, include_logs=false, invalid log stream, delete guards, filtered
bulk-clear, and artifact download/delete without spawning a real script.
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.models.artifact import Artifact
from app.models.execution import ExecutionStatus

pytestmark = pytest.mark.asyncio


class TestListExecutionsSearch:
    async def test_search_matches_stdout(
        self, test_client: AsyncClient, execution_factory, sample_script
    ):
        await execution_factory(script_id=sample_script.id, stdout="needle-in-haystack")
        await execution_factory(script_id=sample_script.id, stdout="nothing here")

        resp = await test_client.get("/api/executions", params={"search": "needle-in"})
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    async def test_search_matches_script_name(
        self, test_client: AsyncClient, execution_factory, script_factory
    ):
        script = await script_factory(name="findable-script-exec")
        await execution_factory(script_id=script.id)

        resp = await test_client.get("/api/executions", params={"search": "findable-script"})
        assert resp.json()["total"] == 1

    async def test_invalid_script_id_returns_400(self, test_client: AsyncClient):
        resp = await test_client.get(
            "/api/executions", params={"script_id": "not-a-number"}
        )
        assert resp.status_code == 400


class TestGetExecution:
    async def test_include_logs_false_hides_stdout_stderr(
        self, test_client: AsyncClient, execution_factory, sample_script
    ):
        execution = await execution_factory(
            script_id=sample_script.id, stdout="secret output", stderr="secret error"
        )
        resp = await test_client.get(
            f"/api/executions/{execution.id}", params={"include_logs": "false"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["stdout"] == ""
        assert data["stderr"] == ""

    async def test_log_stream_type_must_be_stdout_or_stderr(
        self, test_client: AsyncClient, sample_execution
    ):
        resp = await test_client.get(f"/api/executions/{sample_execution.id}/logs/combined")
        assert resp.status_code == 404

    async def test_log_download_sets_content_disposition(
        self, test_client: AsyncClient, execution_factory, sample_script
    ):
        execution = await execution_factory(script_id=sample_script.id, stdout="line1\nline2\n")
        resp = await test_client.get(
            f"/api/executions/{execution.id}/logs/stdout", params={"download": "true"}
        )
        assert resp.status_code == 200
        assert (
            resp.headers["content-disposition"]
            == f'attachment; filename="execution-{execution.id}-stdout.log"'
        )

    async def test_log_tail_lines_limits_output(
        self, test_client: AsyncClient, execution_factory, sample_script
    ):
        execution = await execution_factory(
            script_id=sample_script.id, stdout="a\nb\nc\nd\n"
        )
        resp = await test_client.get(
            f"/api/executions/{execution.id}/logs/stdout", params={"tail_lines": 2}
        )
        assert resp.text == "c\nd\n"
        assert resp.headers["x-log-total-lines"] == "4"
        assert resp.headers["x-log-displayed-lines"] == "2"


class TestCancelExecution:
    async def test_cancel_not_found(self, test_client: AsyncClient):
        resp = await test_client.post("/api/executions/99999/cancel")
        assert resp.status_code == 404

    async def test_cancel_running_execution_succeeds(
        self, test_client: AsyncClient, execution_factory, sample_script
    ):
        execution = await execution_factory(
            script_id=sample_script.id, status=ExecutionStatus.RUNNING.value
        )
        with patch("app.api.executions.executor_service") as mock_exec:
            mock_exec.cancel_execution = AsyncMock(return_value=True)
            resp = await test_client.post(f"/api/executions/{execution.id}/cancel")
        assert resp.status_code == 200
        mock_exec.cancel_execution.assert_awaited_once_with(execution.id)

    async def test_cancel_failure_when_already_finished(
        self, test_client: AsyncClient, execution_factory, sample_script, db_session
    ):
        execution = await execution_factory(
            script_id=sample_script.id, status=ExecutionStatus.RUNNING.value
        )

        async def _finish_it_during_cancel(_execution_id):
            execution.status = ExecutionStatus.SUCCESS.value
            db_session.add(execution)
            await db_session.commit()
            return False

        with patch("app.api.executions.executor_service") as mock_exec:
            mock_exec.cancel_execution = AsyncMock(side_effect=_finish_it_during_cancel)
            resp = await test_client.post(f"/api/executions/{execution.id}/cancel")
        assert resp.status_code == 400
        assert "already finished" in resp.json()["detail"]

    async def test_cancel_failure_generic_500(
        self, test_client: AsyncClient, execution_factory, sample_script
    ):
        execution = await execution_factory(
            script_id=sample_script.id, status=ExecutionStatus.RUNNING.value
        )
        with patch("app.api.executions.executor_service") as mock_exec:
            mock_exec.cancel_execution = AsyncMock(return_value=False)
            resp = await test_client.post(f"/api/executions/{execution.id}/cancel")
        assert resp.status_code == 500


class TestDeleteExecutionGuards:
    async def test_cannot_delete_running_execution(
        self, test_client: AsyncClient, execution_factory, sample_script
    ):
        execution = await execution_factory(
            script_id=sample_script.id, status=ExecutionStatus.RUNNING.value
        )
        resp = await test_client.delete(f"/api/executions/{execution.id}")
        assert resp.status_code == 400

    async def test_delete_finished_execution_succeeds(
        self, test_client: AsyncClient, sample_execution
    ):
        resp = await test_client.delete(f"/api/executions/{sample_execution.id}")
        assert resp.status_code == 200

        resp = await test_client.get(f"/api/executions/{sample_execution.id}")
        assert resp.status_code == 404


class TestClearOldExecutions:
    async def test_clear_filters_by_script_id(
        self, test_client: AsyncClient, execution_factory, script_factory
    ):
        from datetime import UTC, datetime, timedelta

        target = await script_factory(name="clear-target")
        other = await script_factory(name="clear-other")

        old_ts = datetime.now(UTC) - timedelta(days=90)
        await execution_factory(
            script_id=target.id, status=ExecutionStatus.SUCCESS.value, started_at=old_ts
        )
        await execution_factory(
            script_id=other.id, status=ExecutionStatus.SUCCESS.value, started_at=old_ts
        )

        resp = await test_client.delete(
            "/api/executions", params={"days": 30, "script_id": str(target.id)}
        )
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 1

        remaining = await test_client.get(
            "/api/executions", params={"script_id": str(other.id)}
        )
        assert remaining.json()["total"] == 1

    async def test_clear_never_deletes_running_executions(
        self, test_client: AsyncClient, execution_factory, sample_script
    ):
        from datetime import UTC, datetime, timedelta

        old_ts = datetime.now(UTC) - timedelta(days=90)
        await execution_factory(
            script_id=sample_script.id,
            status=ExecutionStatus.RUNNING.value,
            started_at=old_ts,
        )

        resp = await test_client.delete("/api/executions", params={"days": 30})
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 0


class TestExecutionStatsScriptFilter:
    async def test_invalid_script_id_returns_400(self, test_client: AsyncClient):
        resp = await test_client.get(
            "/api/executions/stats", params={"script_id": "not-a-number"}
        )
        assert resp.status_code == 400

    async def test_stats_scoped_to_one_script(
        self, test_client: AsyncClient, execution_factory, script_factory
    ):
        a = await script_factory(name="stats-a")
        b = await script_factory(name="stats-b")
        await execution_factory(script_id=a.id, status=ExecutionStatus.SUCCESS.value)
        await execution_factory(script_id=b.id, status=ExecutionStatus.FAILED.value)

        resp = await test_client.get("/api/executions/stats", params={"script_id": str(a.id)})
        data = resp.json()
        assert data["total_executions"] == 1
        assert data["successful"] == 1
        assert data["failed"] == 0


class TestArtifactsWithoutRealExecution:
    async def test_download_artifact_missing_on_disk_404(
        self, test_client: AsyncClient, sample_execution, db_session
    ):
        artifact = Artifact(
            execution_id=sample_execution.id,
            filename="20260101-gone.txt",
            original_filename="gone.txt",
            size_bytes=5,
        )
        db_session.add(artifact)
        await db_session.commit()
        await db_session.refresh(artifact)

        resp = await test_client.get(
            f"/api/executions/{sample_execution.id}/artifacts/{artifact.id}"
        )
        assert resp.status_code == 404

    async def test_delete_artifact_decrements_execution_counters(
        self, test_client: AsyncClient, execution_factory, sample_script, db_session
    ):
        execution = await execution_factory(
            script_id=sample_script.id,
            artifacts_count=1,
            artifacts_size_bytes=100,
        )
        artifact = Artifact(
            execution_id=execution.id,
            filename="20260101-a.txt",
            original_filename="a.txt",
            size_bytes=100,
        )
        db_session.add(artifact)
        await db_session.commit()
        await db_session.refresh(artifact)

        resp = await test_client.delete(
            f"/api/executions/{execution.id}/artifacts/{artifact.id}"
        )
        assert resp.status_code == 200

        refreshed = await test_client.get(f"/api/executions/{execution.id}")
        assert refreshed.json()["artifacts_count"] == 0
        assert refreshed.json()["artifacts_size_bytes"] == 0

    async def test_delete_unknown_artifact_404(
        self, test_client: AsyncClient, sample_execution
    ):
        resp = await test_client.delete(
            f"/api/executions/{sample_execution.id}/artifacts/99999"
        )
        assert resp.status_code == 404

    async def test_list_artifacts_for_unknown_execution_404(self, test_client: AsyncClient):
        resp = await test_client.get("/api/executions/99999/artifacts")
        assert resp.status_code == 404
