"""Integration tests for Scripts API."""

import pytest
from httpx import AsyncClient


class TestScriptsAPI:
    """Integration tests for /api/scripts endpoints."""

    @pytest.mark.asyncio
    async def test_list_scripts_empty(self, test_client: AsyncClient):
        """Test listing scripts when empty."""
        response = await test_client.get("/api/scripts")
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_create_script(self, test_client: AsyncClient):
        """Test creating a new script."""
        script_data = {
            "name": "api_test_script",
            "description": "Test script via API",
            "content": "print('Hello from API test')",
            "cron_expression": "0 * * * *",
            "python_version": "3.11",
        }
        
        response = await test_client.post("/api/scripts", json=script_data)
        assert response.status_code == 201
        
        data = response.json()
        assert data["name"] == "api_test_script"
        assert data["enabled"] is True
        assert "id" in data

    @pytest.mark.asyncio
    async def test_create_script_duplicate_name(self, test_client: AsyncClient, sample_script):
        """Test creating script with duplicate name fails."""
        script_data = {
            "name": sample_script.name,  # same name
            "content": "print('duplicate')",
            "cron_expression": "0 * * * *",
        }
        
        response = await test_client.post("/api/scripts", json=script_data)
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_get_script(self, test_client: AsyncClient, sample_script):
        """Test getting a script by ID."""
        response = await test_client.get(f"/api/scripts/{sample_script.id}")
        assert response.status_code == 200
        
        data = response.json()
        assert data["id"] == sample_script.id
        assert data["name"] == sample_script.name

    @pytest.mark.asyncio
    async def test_get_script_not_found(self, test_client: AsyncClient):
        """Test getting non-existent script."""
        response = await test_client.get("/api/scripts/99999")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_script(self, test_client: AsyncClient, sample_script):
        """Test updating a script."""
        update_data = {
            "name": sample_script.name,
            "description": "Updated description",
            "content": sample_script.content,
            "cron_expression": sample_script.cron_expression,
            "timeout": 7200,
        }
        
        # API uses PUT, not PATCH
        response = await test_client.put(
            f"/api/scripts/{sample_script.id}",
            json=update_data,
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["description"] == "Updated description"
        assert data["timeout"] == 7200

    @pytest.mark.asyncio
    async def test_delete_script(self, test_client: AsyncClient, script_factory):
        """Test deleting a script."""
        script = await script_factory(name="to_delete")
        
        response = await test_client.delete(f"/api/scripts/{script.id}")
        # API returns 204 No Content on successful delete
        assert response.status_code in [200, 204]
        
        # Verify it's deleted
        get_response = await test_client.get(f"/api/scripts/{script.id}")
        assert get_response.status_code == 404

    @pytest.mark.asyncio
    async def test_toggle_script(self, test_client: AsyncClient, sample_script):
        """Test toggling script enabled status."""
        original_enabled = sample_script.enabled
        
        response = await test_client.post(f"/api/scripts/{sample_script.id}/toggle")
        assert response.status_code == 200
        
        data = response.json()
        assert data["enabled"] is not original_enabled

    @pytest.mark.asyncio
    async def test_list_scripts_pagination(self, test_client: AsyncClient, script_factory):
        """Test script listing with pagination."""
        # Create multiple scripts
        for i in range(5):
            await script_factory(name=f"page_test_{i}")
        
        # Get first page with 2 per page
        response = await test_client.get("/api/scripts?per_page=2&page=1")
        assert response.status_code == 200
        
        data = response.json()
        assert len(data["items"]) == 2
        assert data["total"] == 5
        assert data["page"] == 1
        assert data["pages"] == 3

    @pytest.mark.asyncio
    async def test_list_scripts_filter_enabled(self, test_client: AsyncClient, script_factory):
        """Test filtering scripts by enabled status."""
        await script_factory(name="enabled_script", enabled=True)
        await script_factory(name="disabled_script", enabled=False)
        
        # Filter enabled only
        response = await test_client.get("/api/scripts?enabled=true")
        assert response.status_code == 200
        
        data = response.json()
        for item in data["items"]:
            assert item["enabled"] is True

    @pytest.mark.asyncio
    async def test_validate_script_syntax(self, test_client: AsyncClient):
        """Test script syntax validation."""
        response = await test_client.post(
            "/api/scripts/validate-script",
            json={"code": "print('valid')"},
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["valid"] is True

    @pytest.mark.asyncio
    async def test_validate_script_invalid_syntax(self, test_client: AsyncClient):
        """Test script validation with syntax error."""
        response = await test_client.post(
            "/api/scripts/validate-script",
            json={"code": "print('invalid"},  # missing closing quote
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["valid"] is False
        assert "errors" in data

