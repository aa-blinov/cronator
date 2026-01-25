"""Integration tests for Settings API."""

import pytest
from httpx import AsyncClient


class TestSettingsAPI:
    """Integration tests for /api/settings endpoints."""

    @pytest.mark.asyncio
    async def test_get_settings(self, test_client: AsyncClient):
        """Test getting current settings."""
        response = await test_client.get("/api/settings")
        assert response.status_code == 200

        data = response.json()
        assert "app_name" in data
        assert "scripts_dir" in data
        assert "default_timeout" in data

    @pytest.mark.asyncio
    async def test_get_scheduler_status(self, test_client: AsyncClient):
        """Test getting scheduler status."""
        response = await test_client.get("/api/settings/scheduler-status")
        assert response.status_code == 200

        data = response.json()
        assert "running" in data
        assert "job_count" in data

    @pytest.mark.asyncio
    async def test_update_settings(self, test_client: AsyncClient):
        """Test updating settings."""
        update_data = {
            "default_timeout": 7200,
        }

        response = await test_client.post(
            "/api/settings/update",
            json=update_data,
        )
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_reload_scheduler(self, test_client: AsyncClient):
        """Test reloading scheduler."""
        response = await test_client.post("/api/settings/reload-scheduler")
        assert response.status_code == 200

        data = response.json()
        # API returns message and job_count
        assert "message" in data
        assert "job_count" in data
