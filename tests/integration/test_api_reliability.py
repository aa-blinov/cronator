"""Integration tests for reliability-related API endpoints."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.models.execution import ExecutionStatus

# ---------------------------------------------------------------------------
# GET /api/scripts/templates
# ---------------------------------------------------------------------------

class TestListTemplates:
    @pytest.mark.asyncio
    async def test_returns_200(self, test_client: AsyncClient):
        response = await test_client.get("/api/scripts/templates")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_returns_items_list(self, test_client: AsyncClient):
        response = await test_client.get("/api/scripts/templates")
        data = response.json()
        assert "items" in data
        assert isinstance(data["items"], list)

    @pytest.mark.asyncio
    async def test_returns_expected_count(self, test_client: AsyncClient):
        response = await test_client.get("/api/scripts/templates")
        data = response.json()
        assert len(data["items"]) == 19

    @pytest.mark.asyncio
    async def test_each_template_has_required_fields(self, test_client: AsyncClient):
        response = await test_client.get("/api/scripts/templates")
        required = {"id", "name", "description", "category", "icon", "code",
                    "cron_expression", "python_version", "timeout"}
        for t in response.json()["items"]:
            missing = required - set(t.keys())
            assert not missing, f"Template {t.get('id')!r} missing fields: {missing}"

    @pytest.mark.asyncio
    async def test_no_duplicate_ids(self, test_client: AsyncClient):
        response = await test_client.get("/api/scripts/templates")
        ids = [t["id"] for t in response.json()["items"]]
        assert len(ids) == len(set(ids))

    @pytest.mark.asyncio
    async def test_does_not_require_auth(self, test_client: AsyncClient):
        """Templates are public — no auth needed to see them."""
        response = await test_client.get("/api/scripts/templates")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_categories_are_valid(self, test_client: AsyncClient):
        valid = {"monitoring", "data", "maintenance", "notification"}
        response = await test_client.get("/api/scripts/templates")
        for t in response.json()["items"]:
            assert t["category"] in valid, f"Unknown category in template {t['id']!r}"


# ---------------------------------------------------------------------------
# POST /api/scripts — reliability fields persisted
# ---------------------------------------------------------------------------

class TestCreateScriptReliabilityFields:
    @pytest.mark.asyncio
    async def test_create_with_retry_count(self, test_client: AsyncClient):
        response = await test_client.post("/api/scripts", json={
            "name": "retry-script",
            "content": "print('hi')",
            "cron_expression": "0 * * * *",
            "retry_count": 3,
        })
        assert response.status_code == 201
        assert response.json()["retry_count"] == 3

    @pytest.mark.asyncio
    async def test_create_with_prevent_overlap_false(self, test_client: AsyncClient):
        response = await test_client.post("/api/scripts", json={
            "name": "overlap-script",
            "content": "print('hi')",
            "cron_expression": "0 * * * *",
            "prevent_overlap": False,
        })
        assert response.status_code == 201
        assert response.json()["prevent_overlap"] is False

    @pytest.mark.asyncio
    async def test_create_defaults_prevent_overlap_true(self, test_client: AsyncClient):
        response = await test_client.post("/api/scripts", json={
            "name": "default-overlap",
            "content": "print('hi')",
            "cron_expression": "0 * * * *",
        })
        assert response.status_code == 201
        assert response.json()["prevent_overlap"] is True

    @pytest.mark.asyncio
    async def test_create_defaults_retry_count_zero(self, test_client: AsyncClient):
        response = await test_client.post("/api/scripts", json={
            "name": "default-retry",
            "content": "print('hi')",
            "cron_expression": "0 * * * *",
        })
        assert response.status_code == 201
        assert response.json()["retry_count"] == 0

    @pytest.mark.asyncio
    async def test_create_retry_count_above_max_rejected(self, test_client: AsyncClient):
        response = await test_client.post("/api/scripts", json={
            "name": "bad-retry",
            "content": "print('hi')",
            "cron_expression": "0 * * * *",
            "retry_count": 99,
        })
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_retry_delay_below_min_rejected(self, test_client: AsyncClient):
        response = await test_client.post("/api/scripts", json={
            "name": "bad-delay",
            "content": "print('hi')",
            "cron_expression": "0 * * * *",
            "retry_delay": 1,
        })
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_get_script_returns_stat_fields(self, test_client: AsyncClient, sample_script):
        response = await test_client.get(f"/api/scripts/{sample_script.id}")
        assert response.status_code == 200
        data = response.json()
        assert "consecutive_failures" in data
        assert "last_success_at" in data
        assert "last_failure_at" in data
        assert data["consecutive_failures"] == 0
        assert data["last_success_at"] is None
        assert data["last_failure_at"] is None


# ---------------------------------------------------------------------------
# PUT /api/scripts/{id} — update reliability fields
# ---------------------------------------------------------------------------

class TestUpdateScriptReliabilityFields:
    @pytest.mark.asyncio
    async def test_update_retry_count(self, test_client: AsyncClient, sample_script):
        response = await test_client.put(f"/api/scripts/{sample_script.id}", json={
            "name": sample_script.name,
            "content": sample_script.content,
            "cron_expression": sample_script.cron_expression,
            "retry_count": 2,
        })
        assert response.status_code == 200
        assert response.json()["retry_count"] == 2

    @pytest.mark.asyncio
    async def test_update_prevent_overlap(self, test_client: AsyncClient, sample_script):
        response = await test_client.put(f"/api/scripts/{sample_script.id}", json={
            "name": sample_script.name,
            "content": sample_script.content,
            "cron_expression": sample_script.cron_expression,
            "prevent_overlap": False,
        })
        assert response.status_code == 200
        assert response.json()["prevent_overlap"] is False

    @pytest.mark.asyncio
    async def test_update_all_retry_fields(self, test_client: AsyncClient, sample_script):
        response = await test_client.put(f"/api/scripts/{sample_script.id}", json={
            "name": sample_script.name,
            "content": sample_script.content,
            "cron_expression": sample_script.cron_expression,
            "retry_count": 5,
            "retry_delay": 30,
            "max_retry_window": 600,
        })
        assert response.status_code == 200
        data = response.json()
        assert data["retry_count"] == 5
        assert data["retry_delay"] == 30
        assert data["max_retry_window"] == 600


# ---------------------------------------------------------------------------
# POST /api/scripts/{id}/rerun
# ---------------------------------------------------------------------------

class TestRerunEndpoint:
    @pytest.mark.asyncio
    async def test_rerun_returns_execution_id(self, test_client: AsyncClient, sample_script):
        with patch(
            "app.api.scripts.executor_service.execute_script",
            new_callable=AsyncMock,
            return_value=42,
        ):
            response = await test_client.post(f"/api/scripts/{sample_script.id}/rerun")

        assert response.status_code == 200
        data = response.json()
        assert "execution_id" in data
        assert data["execution_id"] == 42

    @pytest.mark.asyncio
    async def test_rerun_nonexistent_script_returns_404(self, test_client: AsyncClient):
        response = await test_client.post("/api/scripts/99999/rerun")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_rerun_calls_execute_with_manual_trigger(
        self, test_client: AsyncClient, sample_script
    ):
        with patch(
            "app.api.scripts.executor_service.execute_script",
            new_callable=AsyncMock,
            return_value=1,
        ) as mock_execute:
            await test_client.post(f"/api/scripts/{sample_script.id}/rerun")

        mock_execute.assert_called_once_with(
            sample_script.id, triggered_by="manual"
        )

    @pytest.mark.asyncio
    async def test_rerun_while_running_returns_skipped_execution(
        self, test_client: AsyncClient, sample_script, execution_factory
    ):
        """
        When prevent_overlap=True and the script is running,
        execute_script returns a SKIPPED execution id — rerun must still return 200.
        """
        skipped_exec = await execution_factory(
            script_id=sample_script.id,
            status=ExecutionStatus.SKIPPED.value,
        )
        with patch(
            "app.api.scripts.executor_service.execute_script",
            new_callable=AsyncMock,
            return_value=skipped_exec.id,
        ):
            response = await test_client.post(f"/api/scripts/{sample_script.id}/rerun")

        assert response.status_code == 200
        assert response.json()["execution_id"] == skipped_exec.id


# ---------------------------------------------------------------------------
# SKIPPED status in executions API
# ---------------------------------------------------------------------------

class TestSkippedExecutionStatus:
    @pytest.mark.asyncio
    async def test_skipped_execution_visible_in_list(
        self, test_client: AsyncClient, sample_script, execution_factory
    ):
        await execution_factory(
            script_id=sample_script.id,
            status=ExecutionStatus.SKIPPED.value,
            triggered_by="scheduler",
        )
        response = await test_client.get(
            f"/api/executions?script_id={sample_script.id}"
        )
        assert response.status_code == 200
        statuses = [e["status"] for e in response.json()["items"]]
        assert "skipped" in statuses

    @pytest.mark.asyncio
    async def test_skipped_execution_has_zero_duration(
        self, test_client: AsyncClient, sample_script, execution_factory
    ):
        skipped = await execution_factory(
            script_id=sample_script.id,
            status=ExecutionStatus.SKIPPED.value,
            duration_ms=0,
        )
        response = await test_client.get(f"/api/executions/{skipped.id}")
        assert response.status_code == 200
        assert response.json()["duration_ms"] == 0

    @pytest.mark.asyncio
    async def test_filter_by_skipped_status(
        self, test_client: AsyncClient, sample_script, execution_factory
    ):
        await execution_factory(
            script_id=sample_script.id,
            status=ExecutionStatus.SKIPPED.value,
        )
        await execution_factory(
            script_id=sample_script.id,
            status=ExecutionStatus.SUCCESS.value,
        )
        response = await test_client.get("/api/executions?status=skipped")
        assert response.status_code == 200
        items = response.json()["items"]
        assert all(e["status"] == "skipped" for e in items)
        assert len(items) >= 1
