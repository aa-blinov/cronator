"""Integration tests for Executions API."""

import pytest
from httpx import AsyncClient

from app.models.execution import ExecutionStatus


class TestExecutionsAPI:
    """Integration tests for /api/executions endpoints."""

    @pytest.mark.asyncio
    async def test_list_executions_empty(self, test_client: AsyncClient):
        """Test listing executions when empty."""
        response = await test_client.get("/api/executions")
        assert response.status_code == 200

        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_list_executions(self, test_client: AsyncClient, sample_execution):
        """Test listing executions with data."""
        response = await test_client.get("/api/executions")
        assert response.status_code == 200

        data = response.json()
        assert len(data["items"]) >= 1

    @pytest.mark.asyncio
    async def test_get_execution(self, test_client: AsyncClient, sample_execution):
        """Test getting execution by ID."""
        response = await test_client.get(f"/api/executions/{sample_execution.id}")
        assert response.status_code == 200

        data = response.json()
        assert data["id"] == sample_execution.id
        assert data["script_id"] == sample_execution.script_id

    @pytest.mark.asyncio
    async def test_get_execution_not_found(self, test_client: AsyncClient):
        """Test getting non-existent execution."""
        response = await test_client.get("/api/executions/99999")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_list_executions_filter_by_script(
        self, test_client: AsyncClient, sample_execution
    ):
        """Test filtering executions by script_id."""
        response = await test_client.get(f"/api/executions?script_id={sample_execution.script_id}")
        assert response.status_code == 200

        data = response.json()
        for item in data["items"]:
            assert item["script_id"] == sample_execution.script_id

    @pytest.mark.asyncio
    async def test_list_executions_filter_by_status(
        self, test_client: AsyncClient, execution_factory, sample_script
    ):
        """Test filtering executions by status."""
        await execution_factory(
            script_id=sample_script.id,
            status=ExecutionStatus.FAILED.value,
        )

        response = await test_client.get("/api/executions?status=failed")
        assert response.status_code == 200

        data = response.json()
        for item in data["items"]:
            assert item["status"] == "failed"

    @pytest.mark.asyncio
    async def test_get_execution_stats(self, test_client: AsyncClient, sample_execution):
        """Test getting execution statistics."""
        response = await test_client.get("/api/executions/stats")
        assert response.status_code == 200

        data = response.json()
        # API returns success_rate, not total
        assert "success_rate" in data

    @pytest.mark.asyncio
    async def test_get_execution_stats_for_script(self, test_client: AsyncClient, sample_execution):
        """Test getting execution stats for specific script."""
        response = await test_client.get(
            f"/api/executions/stats?script_id={sample_execution.script_id}"
        )
        assert response.status_code == 200

        data = response.json()
        # API returns success_rate
        assert "success_rate" in data

    @pytest.mark.asyncio
    async def test_delete_execution(
        self, test_client: AsyncClient, execution_factory, sample_script
    ):
        """Test deleting an execution."""
        execution = await execution_factory(script_id=sample_script.id)

        response = await test_client.delete(f"/api/executions/{execution.id}")
        assert response.status_code == 200

        # Verify deleted
        get_response = await test_client.get(f"/api/executions/{execution.id}")
        assert get_response.status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_execution_not_running(self, test_client: AsyncClient, sample_execution):
        """Test canceling execution that's not running."""
        # sample_execution has status SUCCESS, so can't be cancelled
        response = await test_client.post(f"/api/executions/{sample_execution.id}/cancel")
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_clear_old_executions(self, test_client: AsyncClient, sample_execution):
        """Test clearing old executions."""
        # Endpoint is DELETE /api/executions?days=30 (not /old)
        response = await test_client.delete("/api/executions?days=30")
        assert response.status_code == 200

        data = response.json()
        assert "deleted" in data
