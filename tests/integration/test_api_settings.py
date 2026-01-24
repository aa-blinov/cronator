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
    async def test_get_git_status(self, test_client: AsyncClient):
        """Test getting git sync status."""
        response = await test_client.get("/api/settings/git-status")
        assert response.status_code == 200

        data = response.json()
        assert "enabled" in data
        assert "repo_url" in data

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

    @pytest.mark.asyncio
    async def test_git_sync_disabled(self, test_client: AsyncClient):
        """Test git sync when disabled."""
        response = await test_client.post("/api/settings/git-sync")
        # When git is disabled, it should return success=False or appropriate message
        assert response.status_code == 200

        data = response.json()
        # Check that response has expected structure
        assert "success" in data or "message" in data
