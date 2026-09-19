"""Integration tests for Artifacts API and system."""

import asyncio
import shutil

import pytest
from httpx import AsyncClient

from app.config import get_settings

settings = get_settings()


async def wait_for_execution_finish(test_client, execution_id, timeout=30):
    """Wait for an execution to finish by polling its status."""
    for _ in range(timeout):
        await asyncio.sleep(1)
        response = await test_client.get(f"/api/executions/{execution_id}")
        if response.status_code == 200:
            status = response.json().get("status")
            if status in ["success", "failed", "timeout"]:
                return True
    return False


@pytest.fixture
def tmp_artifacts_dir(tmp_path, monkeypatch):
    """Use a temporary directory for artifacts during tests."""
    temp_dir = tmp_path / "test_artifacts"
    temp_dir.mkdir()

    # Patch settings
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "artifacts_dir", temp_dir)

    # Also need to make sure the library uses the same path
    # (In tests, the library runs in the same process but might use os.environ)
    monkeypatch.setenv("CRONATOR_ARTIFACTS_DIR", str(temp_dir))

    yield temp_dir

    if temp_dir.exists():
        shutil.rmtree(temp_dir)


@pytest.mark.asyncio
async def test_artifact_lifecycle(test_client: AsyncClient, tmp_artifacts_dir):
    """Test the full lifecycle of an artifact: save, list, download, delete."""

    # 1. Create a script that saves an artifact
    script_data = {
        "name": "test_artifact_script",
        "description": "Script that saves a text artifact",
        "content": (
            "from cronator_lib import save_artifact, get_logger\n"
            "log = get_logger()\n"
            "log.info('Saving artifact...')\n"
            "save_artifact('test_file.txt', 'Hello Artifacts!')\n"
            "log.success('Done')\n"
        ),
        "cron_expression": "0 0 * * *",
        "python_version": "3.12",
        "enabled": False,
    }

    response = await test_client.post("/api/scripts", json=script_data)
    assert response.status_code == 201
    script_id = response.json()["id"]

    try:
        # 2. Run the script
        response = await test_client.post(f"/api/scripts/{script_id}/run")
        assert response.status_code == 200
        execution_id = response.json()["execution_id"]

        # 3. Wait for finish
        if not await wait_for_execution_finish(test_client, execution_id):
            pytest.fail("Script did not finish in time")

        # Check execution status
        response = await test_client.get(f"/api/executions/{execution_id}")
        exec_data = response.json()
        if exec_data["status"] != "success":
            print(f"DEBUG: Script failed! Exit code: {exec_data.get('exit_code')}")
            print(f"DEBUG: Stdout: {exec_data.get('stdout')}")
            print(f"DEBUG: Stderr: {exec_data.get('stderr')}")
            print(f"DEBUG: Error: {exec_data.get('error_message')}")
            assert exec_data["status"] == "success"

        # 4. List artifacts for execution
        response = await test_client.get(f"/api/executions/{execution_id}/artifacts")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1
        artifact = data["items"][0]
        assert artifact["original_filename"] == "test_file.txt"
        artifact_id = artifact["id"]

        # 5. Download and verify content
        response = await test_client.get(f"/api/executions/{execution_id}/artifacts/{artifact_id}")
        assert response.status_code == 200
        assert response.text == "Hello Artifacts!"
        assert response.headers["content-disposition"] == 'attachment; filename="test_file.txt"'

        # 6. Delete artifact
        response = await test_client.delete(
            f"/api/executions/{execution_id}/artifacts/{artifact_id}"
        )
        assert response.status_code == 200

        # 7. Verify deleted from DB and filesystem
        response = await test_client.get(f"/api/executions/{execution_id}/artifacts")
        assert len(response.json()["items"]) == 0

        # Check file is gone from disk
        artifact_file = tmp_artifacts_dir / str(execution_id) / artifact["filename"]
        assert not artifact_file.exists()

    finally:
        await test_client.delete(f"/api/scripts/{script_id}")


@pytest.mark.asyncio
async def test_binary_artifact_support(test_client: AsyncClient, tmp_artifacts_dir):
    """Test saving and downloading binary files."""

    # Binary data (simulating a small file)
    binary_data = b"\x00\x01\x02\x03\xff\xfe\xfd"

    # Script that saves binary data
    # Note: we pass bytes directly to save_artifact
    script_data = {
        "name": "test_binary_script",
        "content": (
            "from cronator_lib import save_artifact\n"
            f"save_artifact('binary.dat', {repr(binary_data)})\n"
        ),
        "python_version": "3.12",
        "enabled": False,
    }

    response = await test_client.post("/api/scripts", json=script_data)
    script_id = response.json()["id"]

    try:
        response = await test_client.post(f"/api/scripts/{script_id}/run")
        execution_id = response.json()["execution_id"]
        await wait_for_execution_finish(test_client, execution_id)

        # Get artifact
        resp = await test_client.get(f"/api/executions/{execution_id}/artifacts")
        artifact_id = resp.json()["items"][0]["id"]

        # Download and compare bytes
        response = await test_client.get(f"/api/executions/{execution_id}/artifacts/{artifact_id}")
        assert response.status_code == 200
        assert response.content == binary_data

    finally:
        await test_client.delete(f"/api/scripts/{script_id}")


@pytest.mark.asyncio
async def test_cascade_delete_artifacts(test_client: AsyncClient, tmp_artifacts_dir):
    """Test that deleting an execution removes its artifacts."""

    script_data = {
        "name": "test_cascade_script",
        "content": (
            "from cronator_lib import save_artifact\n"
            "save_artifact('file1.txt', 'data1')\n"
            "save_artifact('file2.txt', 'data2')\n"
        ),
        "python_version": "3.12",
        "enabled": False,
    }

    response = await test_client.post("/api/scripts", json=script_data)
    script_id = response.json()["id"]

    try:
        response = await test_client.post(f"/api/scripts/{script_id}/run")
        execution_id = response.json()["execution_id"]
        await wait_for_execution_finish(test_client, execution_id)

        # Confirm artifacts exist on disk
        exec_artifacts_dir = tmp_artifacts_dir / str(execution_id)
        assert exec_artifacts_dir.exists()
        assert len(list(exec_artifacts_dir.glob("*"))) == 2

        # Delete execution
        response = await test_client.delete(f"/api/executions/{execution_id}")
        assert response.status_code == 200

        # Verify directory is gone
        assert not exec_artifacts_dir.exists()

    finally:
        await test_client.delete(f"/api/scripts/{script_id}")


@pytest.mark.asyncio
async def test_clear_all_artifacts_api(test_client: AsyncClient, tmp_artifacts_dir):
    """Test the administrative clear-all-artifacts endpoint."""

    # Create a couple of executions with artifacts
    script_data = {
        "name": "test_clear_all_script",
        "content": (
            "from cronator_lib import save_artifact\nsave_artifact('auto.txt', 'clear me')\n"
        ),
        "python_version": "3.12",
        "enabled": False,
    }

    response = await test_client.post("/api/scripts", json=script_data)
    script_id = response.json()["id"]

    try:
        # Run twice
        for i in range(2):
            # Retry logic in case script is still marked as running
            for attempt in range(5):
                response = await test_client.post(f"/api/scripts/{script_id}/run")
                if response.status_code == 200:
                    execution_id = response.json()["execution_id"]
                    break
                # Script still marked as running, wait and retry
                await asyncio.sleep(0.5)
            else:
                pytest.fail(f"Failed to start script run {i + 1} after retries")

            await wait_for_execution_finish(test_client, execution_id)

        # Confirm we have multiple directories in artifacts_dir
        assert len(list(tmp_artifacts_dir.iterdir())) == 2

        # Call clear-all API
        response = await test_client.post("/api/settings/clear-artifacts")
        assert response.status_code == 200
        assert response.json()["deleted_artifacts"] >= 2
        assert response.json()["deleted_directories"] >= 2
        remaining = [d for d in tmp_artifacts_dir.iterdir() if d.is_dir()]
        assert len(remaining) == 0

    finally:
        await test_client.delete(f"/api/scripts/{script_id}")
