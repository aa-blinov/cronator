"""Coverage for app/api/scripts.py endpoints not exercised elsewhere:
run/test/toggle/rebuild-env/install/packages/validate-dependencies, plus
the update/delete/create edge cases (rename conflicts, running-script
guards, filesystem error paths).
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _create_script(client: AsyncClient, name: str, **kwargs) -> dict:
    payload = {"name": name, "content": "print('hi')", "cron_expression": "0 * * * *"}
    payload.update(kwargs)
    resp = await client.post("/api/scripts", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestRunAndTest:
    async def test_run_script_starts_execution(self, test_client: AsyncClient, script_factory):
        script = await script_factory(name="run-me")
        with patch("app.api.scripts.executor_service") as mock_exec:
            mock_exec.execute_script = AsyncMock(return_value=42)
            resp = await test_client.post(f"/api/scripts/{script.id}/run")
        assert resp.status_code == 200, resp.text
        assert resp.json()["execution_id"] == 42
        mock_exec.execute_script.assert_awaited_once_with(script.id, triggered_by="manual")

    async def test_run_unknown_script_404(self, test_client: AsyncClient):
        resp = await test_client.post("/api/scripts/99999/run")
        assert resp.status_code == 404

    async def test_test_script_marks_is_test(self, test_client: AsyncClient, script_factory):
        script = await script_factory(name="test-me")
        with patch("app.api.scripts.executor_service") as mock_exec:
            mock_exec.is_script_running.return_value = False
            mock_exec.execute_script = AsyncMock(return_value=7)
            resp = await test_client.post(f"/api/scripts/{script.id}/test")
        assert resp.status_code == 200, resp.text
        mock_exec.execute_script.assert_awaited_once_with(
            script.id, triggered_by="test", is_test=True
        )

    async def test_test_script_conflicts_with_running_script(
        self, test_client: AsyncClient, script_factory
    ):
        script = await script_factory(name="already-running")
        with patch("app.api.scripts.executor_service") as mock_exec:
            mock_exec.is_script_running.return_value = True
            resp = await test_client.post(f"/api/scripts/{script.id}/test")
        assert resp.status_code == 409

    async def test_rerun_script(self, test_client: AsyncClient, script_factory):
        script = await script_factory(name="rerun-me")
        with patch("app.api.scripts.executor_service") as mock_exec:
            mock_exec.execute_script = AsyncMock(return_value=9)
            resp = await test_client.post(f"/api/scripts/{script.id}/rerun")
        assert resp.status_code == 200
        assert resp.json()["execution_id"] == 9


class TestToggle:
    async def test_toggle_flips_enabled_state(self, test_client: AsyncClient, script_factory):
        script = await script_factory(name="toggle-me", enabled=True)
        resp = await test_client.post(f"/api/scripts/{script.id}/toggle")
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

        resp = await test_client.post(f"/api/scripts/{script.id}/toggle")
        assert resp.json()["enabled"] is True

    async def test_toggle_unknown_script_404(self, test_client: AsyncClient):
        resp = await test_client.post("/api/scripts/99999/toggle")
        assert resp.status_code == 404


class TestRebuildEnvironment:
    async def test_rebuild_env_success(self, test_client: AsyncClient, script_factory):
        script = await script_factory(name="rebuild-ok")
        with patch("app.api.scripts.environment_service") as mock_env:
            mock_env.is_script_running = None  # not used by this route
            mock_env.setup_environment = AsyncMock(return_value=(True, "env ready"))
            with patch("app.api.scripts.executor_service") as mock_exec:
                mock_exec.is_script_running.return_value = False
                resp = await test_client.post(f"/api/scripts/{script.id}/rebuild-env")
        assert resp.status_code == 200
        assert resp.json()["message"] == "env ready"

    async def test_rebuild_env_failure_returns_500(self, test_client: AsyncClient, script_factory):
        script = await script_factory(name="rebuild-fail")
        with patch("app.api.scripts.environment_service") as mock_env:
            mock_env.setup_environment = AsyncMock(return_value=(False, "pip explode"))
            with patch("app.api.scripts.executor_service") as mock_exec:
                mock_exec.is_script_running.return_value = False
                resp = await test_client.post(f"/api/scripts/{script.id}/rebuild-env")
        assert resp.status_code == 500
        assert "pip explode" in resp.json()["detail"]

    async def test_rebuild_env_conflicts_while_running(
        self, test_client: AsyncClient, script_factory
    ):
        script = await script_factory(name="rebuild-running")
        with patch("app.api.scripts.executor_service") as mock_exec:
            mock_exec.is_script_running.return_value = True
            resp = await test_client.post(f"/api/scripts/{script.id}/rebuild-env")
        assert resp.status_code == 409


class TestInstallFlow:
    async def test_start_install_enqueues_background_task(
        self, test_client: AsyncClient, script_factory
    ):
        script = await script_factory(name="install-me", dependencies="requests")
        with patch("app.api.scripts.environment_service") as mock_env:
            mock_env.is_installing.return_value = False
            mock_env.install_queues = {}
            with patch("app.api.scripts.executor_service") as mock_exec:
                mock_exec.is_script_running.return_value = False
                resp = await test_client.post(f"/api/scripts/{script.id}/install")
        assert resp.status_code == 200
        assert resp.json() == {"message": "Installation started", "script_id": script.id}

    async def test_start_install_conflicts_when_already_installing(
        self, test_client: AsyncClient, script_factory
    ):
        script = await script_factory(name="install-busy")
        with patch("app.api.scripts.environment_service") as mock_env:
            mock_env.is_installing.return_value = True
            with patch("app.api.scripts.executor_service") as mock_exec:
                mock_exec.is_script_running.return_value = False
                resp = await test_client.post(f"/api/scripts/{script.id}/install")
        assert resp.status_code == 409

    async def test_install_stream_without_active_install_returns_error_event(
        self, test_client: AsyncClient, script_factory
    ):
        script = await script_factory(name="install-stream-idle")
        resp = await test_client.get(f"/api/scripts/{script.id}/install-stream")
        assert resp.status_code == 200
        assert "No installation in progress" in resp.text

    async def test_get_packages(self, test_client: AsyncClient, script_factory):
        script = await script_factory(name="pkg-list")
        with patch("app.api.scripts.environment_service") as mock_env:
            mock_env.get_installed_packages = AsyncMock(return_value=["requests==2.31.0"])
            resp = await test_client.get(f"/api/scripts/{script.id}/packages")
        assert resp.status_code == 200
        assert resp.json() == {"packages": ["requests==2.31.0"]}


class TestValidateDependencies:
    async def test_validate_dependencies_empty(self, test_client: AsyncClient):
        resp = await test_client.post("/api/scripts/validate-dependencies", json={})
        assert resp.status_code == 200
        assert resp.json()["valid"] is True
        assert resp.json()["packages"] == []

    async def test_validate_dependencies_delegates_to_environment_service(
        self, test_client: AsyncClient
    ):
        with patch("app.api.scripts.environment_service") as mock_env:
            mock_env.validate_dependencies = AsyncMock(
                return_value=(False, "unknown package", [])
            )
            resp = await test_client.post(
                "/api/scripts/validate-dependencies",
                json={"dependencies": "not-a-real-pkg==1.0"},
            )
        assert resp.status_code == 200
        assert resp.json() == {
            "valid": False,
            "message": "unknown package",
            "packages": [],
        }


class TestUpdateScriptEdgeCases:
    async def test_update_rejects_rename_to_existing_name(
        self, test_client: AsyncClient, script_factory
    ):
        await script_factory(name="taken")
        other = await script_factory(name="renaming")
        resp = await test_client.put(f"/api/scripts/{other.id}", json={"name": "taken"})
        assert resp.status_code == 400

    async def test_update_content_rewrites_file_and_path(
        self, test_client: AsyncClient
    ):
        script = await _create_script(test_client, "content-rewrite")
        resp = await test_client.put(
            f"/api/scripts/{script['id']}", json={"content": "print('new')"}
        )
        assert resp.status_code == 200
        assert resp.json()["path"] == "content-rewrite/script.py"

    async def test_update_unknown_script_404(self, test_client: AsyncClient):
        resp = await test_client.put("/api/scripts/99999", json={"description": "x"})
        assert resp.status_code == 404

    async def test_update_with_custom_validator_rejection_returns_422_not_500(
        self, test_client: AsyncClient, script_factory
    ):
        """A pydantic field_validator raising ValueError (e.g. `name` too
        short) must surface as a normal 422, not crash the validation
        exception handler — see app/main.py's validation_exception_handler.
        """
        script = await script_factory(name="short-name-target")
        resp = await test_client.put(f"/api/scripts/{script.id}", json={"name": "x"})
        assert resp.status_code == 422
        assert "at least 2 characters" in resp.text

    async def test_update_invalid_dependencies_rejected(
        self, test_client: AsyncClient, script_factory
    ):
        script = await script_factory(name="bad-deps-update")
        with patch("app.api.scripts.environment_service") as mock_env:
            mock_env.validate_dependencies = AsyncMock(return_value=(False, "bad spec", []))
            resp = await test_client.put(
                f"/api/scripts/{script.id}", json={"dependencies": "???"}
            )
        assert resp.status_code == 400
        assert "bad spec" in resp.json()["detail"]


class TestDeleteScriptGuards:
    async def test_delete_blocked_while_running(self, test_client: AsyncClient, script_factory):
        script = await script_factory(name="delete-running")
        with patch("app.api.scripts.executor_service") as mock_exec:
            mock_exec.is_script_running.return_value = True
            resp = await test_client.delete(f"/api/scripts/{script.id}")
        assert resp.status_code == 409

    async def test_delete_succeeds_even_if_env_cleanup_fails(
        self, test_client: AsyncClient, script_factory
    ):
        script = await script_factory(name="delete-env-fails")
        with patch("app.api.scripts.executor_service") as mock_exec:
            mock_exec.is_script_running.return_value = False
            with patch("app.api.scripts.environment_service") as mock_env:
                mock_env.delete_env = AsyncMock(return_value=(False, "venv busy"))
                resp = await test_client.delete(f"/api/scripts/{script.id}")
        assert resp.status_code == 204

        resp = await test_client.get(f"/api/scripts/{script.id}")
        assert resp.status_code == 404


class TestCreateScriptDependencyValidation:
    async def test_create_rejects_invalid_dependencies(self, test_client: AsyncClient):
        with patch("app.api.scripts.environment_service") as mock_env:
            mock_env.validate_dependencies = AsyncMock(return_value=(False, "bad spec", []))
            resp = await test_client.post(
                "/api/scripts",
                json={
                    "name": "invalid-deps-script",
                    "content": "print(1)",
                    "cron_expression": "0 * * * *",
                    "dependencies": "???",
                },
            )
        assert resp.status_code == 400
        assert "bad spec" in resp.json()["detail"]


class TestAuditLog:
    async def test_audit_log_unknown_script_404(self, test_client: AsyncClient):
        resp = await test_client.get("/api/scripts/99999/audit")
        assert resp.status_code == 404

    async def test_audit_log_lists_field_changes(self, test_client: AsyncClient):
        script = await _create_script(test_client, "audited-script")
        await test_client.put(
            f"/api/scripts/{script['id']}", json={"cron_expression": "5 5 * * *"}
        )

        resp = await test_client.get(f"/api/scripts/{script['id']}/audit")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert any(item["field_name"] == "cron_expression" for item in data["items"])


class TestListScriptsSearch:
    async def test_search_matches_by_name(self, test_client: AsyncClient, script_factory):
        await script_factory(name="findable-abc")
        await script_factory(name="other-script")

        resp = await test_client.get("/api/scripts", params={"search": "findable"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "findable-abc"
