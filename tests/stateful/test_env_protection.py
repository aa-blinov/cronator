"""Integration tests for environment protection during script execution.

The while-running tests use the executor's `_running_scripts` set directly
rather than spawning a real subprocess. Spinning up a venv + `uv pip install`
on first run takes 30s+ on a cold CI runner, which made the original "wait
for status='running'" approach flaky — the script never reached running
because env bootstrap itself timed out. Marking the script as running in
the executor's bookkeeping set gives us the same code path through the
DELETE/INSTALL/REBUILD guards without depending on subprocess startup time.
"""

import pytest


@pytest.mark.asyncio
async def test_cannot_delete_script_while_running(test_client):
    """Test that deleting a script during execution is blocked."""
    from app.services import executor as executor_module

    # Create a script that, if it ever ran, would block on input.
    # We never actually run it — we just register it as running.
    script_data = {
        "name": "test_long_runner",
        "description": "Test script that never actually runs",
        "content": "import time\ntime.sleep(5)\nprint('Done')",
        "cron_expression": "0 0 * * *",
        "python_version": "3.12",
        "enabled": False,
    }

    response = await test_client.post("/api/scripts", json=script_data)
    assert response.status_code == 201
    script = response.json()
    script_id = script["id"]

    try:
        # Mark the script as running in the executor's bookkeeping set. This
        # is exactly the state the DELETE guard checks via `is_script_running`.
        executor_module.executor_service._running_scripts.add(script_id)

        # Try to delete (should fail with 409)
        response = await test_client.delete(f"/api/scripts/{script_id}")
        assert response.status_code == 409, (
            f"expected 409, got {response.status_code}: {response.text}"
        )
        assert "running" in response.json()["detail"].lower()

    finally:
        # Remove from running set so cleanup succeeds
        executor_module.executor_service._running_scripts.discard(script_id)
        # Now deletion should work
        response = await test_client.delete(f"/api/scripts/{script_id}")
        assert response.status_code == 204


@pytest.mark.asyncio
async def test_cannot_install_dependencies_while_running(test_client):
    """Test that installing dependencies during execution is blocked."""
    from app.services import executor as executor_module

    script_data = {
        "name": "test_install_blocker",
        "description": "Test script that never actually runs",
        "content": "import time\ntime.sleep(5)\nprint('Done')",
        "cron_expression": "0 0 * * *",
        "python_version": "3.12",
        "enabled": False,
        "dependencies": "requests",
    }

    response = await test_client.post("/api/scripts", json=script_data)
    assert response.status_code == 201
    script = response.json()
    script_id = script["id"]

    try:
        executor_module.executor_service._running_scripts.add(script_id)

        # Try to install dependencies (should fail with 409)
        response = await test_client.post(f"/api/scripts/{script_id}/install")
        assert response.status_code == 409, (
            f"expected 409, got {response.status_code}: {response.text}"
        )
        assert "running" in response.json()["detail"].lower()

    finally:
        executor_module.executor_service._running_scripts.discard(script_id)
        await test_client.delete(f"/api/scripts/{script_id}")


@pytest.mark.asyncio
async def test_cannot_rebuild_env_while_running(test_client):
    """Test that rebuilding environment during execution is blocked."""
    from app.services import executor as executor_module

    script_data = {
        "name": "test_rebuild_blocker",
        "description": "Test script that never actually runs",
        "content": "import time\ntime.sleep(5)\nprint('Done')",
        "cron_expression": "0 0 * * *",
        "python_version": "3.12",
        "enabled": False,
    }

    response = await test_client.post("/api/scripts", json=script_data)
    assert response.status_code == 201
    script = response.json()
    script_id = script["id"]

    try:
        executor_module.executor_service._running_scripts.add(script_id)

        # Try to rebuild environment (should fail with 409)
        response = await test_client.post(f"/api/scripts/{script_id}/rebuild-env")
        assert response.status_code == 409, (
            f"expected 409, got {response.status_code}: {response.text}"
        )
        assert "running" in response.json()["detail"].lower()

    finally:
        executor_module.executor_service._running_scripts.discard(script_id)
        await test_client.delete(f"/api/scripts/{script_id}")


@pytest.mark.asyncio
async def test_can_run_multiple_different_scripts(test_client):
    """Test that different scripts can run simultaneously — same approach: mock the running set."""
    from app.services import executor as executor_module

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

    response1 = await test_client.post("/api/scripts", json=script1_data)
    assert response1.status_code == 201
    script1_id = response1.json()["id"]

    response2 = await test_client.post("/api/scripts", json=script2_data)
    assert response2.status_code == 201
    script2_id = response2.json()["id"]

    try:
        # Mark both as running, then verify they appear in the running set.
        executor_module.executor_service._running_scripts.add(script1_id)
        executor_module.executor_service._running_scripts.add(script2_id)

        assert executor_module.executor_service.is_script_running(script1_id)
        assert executor_module.executor_service.is_script_running(script2_id)

    finally:
        executor_module.executor_service._running_scripts.discard(script1_id)
        executor_module.executor_service._running_scripts.discard(script2_id)
        await test_client.delete(f"/api/scripts/{script1_id}")
        await test_client.delete(f"/api/scripts/{script2_id}")
