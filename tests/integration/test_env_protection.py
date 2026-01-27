"""Integration tests for environment protection during script execution."""

import asyncio

import pytest


async def wait_for_script_finish(test_client, script_id, timeout=30):
    """Wait for a script execution to finish by polling its status."""
    for _ in range(timeout):
        await asyncio.sleep(1)
        response = await test_client.get(f"/api/scripts/{script_id}")
        if response.status_code == 200:
            status = response.json().get("last_run_status")
            if status != "running":
                return True
    return False


@pytest.mark.asyncio
async def test_cannot_delete_script_while_running(test_client):
    """Test that deleting a script during execution is blocked."""
    # Create a long-running script
    script_data = {
        "name": "test_long_runner",
        "description": "Test script that runs for a few seconds",
        "content": "import time\ntime.sleep(5)\nprint('Done')",
        "cron_expression": "0 0 * * *",
        "python_version": "3.12",
        "enabled": False,
    }

    # Create script
    response = await test_client.post("/api/scripts", json=script_data)
    assert response.status_code == 201
    script = response.json()
    script_id = script["id"]

    try:
        # Start execution
        response = await test_client.post(f"/api/scripts/{script_id}/run")
        assert response.status_code == 200

        # Wait a bit to ensure script is running
        await asyncio.sleep(1)

        # Try to delete (should fail with 409)
        response = await test_client.delete(f"/api/scripts/{script_id}")
        assert response.status_code == 409
        assert "running" in response.json()["detail"].lower()

        # Wait for script to finish
        assert await wait_for_script_finish(test_client, script_id), "Script did not finish in time"

        # Now deletion should work
        response = await test_client.delete(f"/api/scripts/{script_id}")
        assert response.status_code == 204

    except Exception:
        # Emergency cleanup - wait a bit more then try to delete
        await asyncio.sleep(10)
        await test_client.delete(f"/api/scripts/{script_id}")
        raise


@pytest.mark.asyncio
async def test_cannot_install_dependencies_while_running(test_client):
    """Test that installing dependencies during execution is blocked."""
    # Create a long-running script
    script_data = {
        "name": "test_install_blocker",
        "description": "Test script that runs for a few seconds",
        "content": "import time\ntime.sleep(5)\nprint('Done')",
        "cron_expression": "0 0 * * *",
        "python_version": "3.12",
        "enabled": False,
        "dependencies": "requests",
    }

    # Create script
    response = await test_client.post("/api/scripts", json=script_data)
    assert response.status_code == 201
    script = response.json()
    script_id = script["id"]

    try:
        # Start execution
        response = await test_client.post(f"/api/scripts/{script_id}/run")
        assert response.status_code == 200

        # Wait a bit to ensure script is running
        await asyncio.sleep(1)

        # Try to install dependencies (should fail with 409)
        response = await test_client.post(f"/api/scripts/{script_id}/install")
        assert response.status_code == 409
        assert "running" in response.json()["detail"].lower()

        # Wait for script to finish
        await wait_for_script_finish(test_client, script_id)

    finally:
        # Cleanup
        await test_client.delete(f"/api/scripts/{script_id}")


@pytest.mark.asyncio
async def test_cannot_rebuild_env_while_running(test_client):
    """Test that rebuilding environment during execution is blocked."""
    # Create a long-running script
    script_data = {
        "name": "test_rebuild_blocker",
        "description": "Test script that runs for a few seconds",
        "content": "import time\ntime.sleep(5)\nprint('Done')",
        "cron_expression": "0 0 * * *",
        "python_version": "3.12",
        "enabled": False,
    }

    # Create script
    response = await test_client.post("/api/scripts", json=script_data)
    assert response.status_code == 201
    script = response.json()
    script_id = script["id"]

    try:
        # Start execution
        response = await test_client.post(f"/api/scripts/{script_id}/run")
        assert response.status_code == 200

        # Wait a bit to ensure script is running
        await asyncio.sleep(1)

        # Try to rebuild environment (should fail with 409)
        response = await test_client.post(f"/api/scripts/{script_id}/rebuild-env")
        assert response.status_code == 409
        assert "running" in response.json()["detail"].lower()

        # Wait for script to finish
        await wait_for_script_finish(test_client, script_id)

    finally:
        # Cleanup
        await test_client.delete(f"/api/scripts/{script_id}")


@pytest.mark.asyncio
async def test_can_run_multiple_different_scripts(test_client):
    """Test that different scripts can run simultaneously."""
    # Create two different scripts
    script1_data = {
        "name": "test_concurrent_1",
        "description": "First concurrent script",
        "content": "import time\ntime.sleep(2)\nprint('Script 1 done')",
        "cron_expression": "0 0 * * *",
        "python_version": "3.12",
        "enabled": False,
    }

    script2_data = {
        "name": "test_concurrent_2",
        "description": "Second concurrent script",
        "content": "import time\ntime.sleep(2)\nprint('Script 2 done')",
        "cron_expression": "0 0 * * *",
        "python_version": "3.12",
        "enabled": False,
    }

    # Create scripts
    response1 = await test_client.post("/api/scripts", json=script1_data)
    assert response1.status_code == 201
    script1_id = response1.json()["id"]

    response2 = await test_client.post("/api/scripts", json=script2_data)
    assert response2.status_code == 201
    script2_id = response2.json()["id"]

    try:
        # Start both scripts
        response1 = await test_client.post(f"/api/scripts/{script1_id}/run")
        assert response1.status_code == 200

        response2 = await test_client.post(f"/api/scripts/{script2_id}/run")
        assert response2.status_code == 200

        # Both should be running
        await asyncio.sleep(1)

        # Wait for completion
        await wait_for_script_finish(test_client, script1_id)
        await wait_for_script_finish(test_client, script2_id)

    finally:
        # Cleanup
        await test_client.delete(f"/api/scripts/{script1_id}")
        await test_client.delete(f"/api/scripts/{script2_id}")
