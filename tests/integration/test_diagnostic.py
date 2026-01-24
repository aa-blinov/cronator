"""Quick diagnostic test to check registration."""

import asyncio

import pytest


@pytest.mark.asyncio
async def test_script_registration_diagnostic(test_client):
    """Diagnostic test to see if scripts get registered."""
    from app.services.environment import environment_service
    from app.services.executor import executor_service

    # Create a script
    script_data = {
        "name": "diagnostic_script",
        "description": "Test diagnostic",
        "content": "import time\ntime.sleep(5)\nprint('done')",
        "cron_expression": "0 0 * * *",
        "python_version": "3.11",
        "enabled": False,
    }

    response = await test_client.post("/api/scripts", json=script_data)
    assert response.status_code == 201
    script = response.json()
    script_id = script["id"]

    # Check executor_service instance ID
    from app.api.scripts import executor_service as api_executor_service

    print("\n=== DIAGNOSTIC ===")
    print(f"Script created: ID={script_id}, name={script['name']}")
    print(f"Script name to ID mapping: {environment_service._script_name_to_id}")
    print(f"Is registered: {'diagnostic_script' in environment_service._script_name_to_id}")
    print(f"Test executor_service ID: {id(executor_service)}")
    print(f"API executor_service ID: {id(api_executor_service)}")
    print(f"Same instance: {executor_service is api_executor_service}")

    # Start execution
    response = await test_client.post(f"/api/scripts/{script_id}/run")
    print(f"Run response: {response.status_code}")
    if response.status_code == 200:
        print(f"Run response data: {response.json()}")

    await asyncio.sleep(0.5)

    # Check if running
    is_running_env = environment_service.is_script_running("diagnostic_script")
    is_running_exec = executor_service.is_script_running(script_id)

    print(f"Is running (via environment_service): {is_running_env}")
    print(f"Is running (via executor_service): {is_running_exec}")
    print(f"Running scripts IDs: {executor_service._running_scripts}")

    # Cleanup
    await asyncio.sleep(1)
    await test_client.delete(f"/api/scripts/{script_id}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
