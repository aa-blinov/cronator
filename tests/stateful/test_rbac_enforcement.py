"""RBAC enforcement — real Basic Auth, not the test_client's blanket
verify_credentials override (which always resolves as admin, so every
other test file in this suite would silently pass regardless of role
gating). These tests remove that override for the duration of each test
and authenticate as an actual DB-backed viewer/admin user instead.
"""

import base64

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import verify_credentials
from app.main import app as fastapi_app
from app.services.user_service import create_user

pytestmark = pytest.mark.asyncio


def _basic_auth_header(username: str, password: str) -> dict:
    token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
async def real_auth_client(test_client):
    """A client on the same app/DB as test_client, but with real Basic
    Auth instead of the blanket verify_credentials override."""
    del fastapi_app.dependency_overrides[verify_credentials]
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    # test_client's own teardown clears all overrides anyway, but restore
    # this one explicitly in case a later fixture in this test relies on it.
    fastapi_app.dependency_overrides[verify_credentials] = lambda: "test_user"


class TestViewerIsReadOnly:
    async def test_viewer_can_list_scripts(self, test_client, real_auth_client, script_factory):
        await create_user("a-viewer", "viewer-password-123", role="viewer")
        await script_factory(name="viewer-visible")

        resp = await real_auth_client.get(
            "/api/scripts", headers=_basic_auth_header("a-viewer", "viewer-password-123")
        )
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1

    async def test_viewer_cannot_create_script(self, test_client, real_auth_client):
        await create_user("viewer-create", "viewer-password-123", role="viewer")

        resp = await real_auth_client.post(
            "/api/scripts",
            json={"name": "blocked-script", "content": "print(1)"},
            headers=_basic_auth_header("viewer-create", "viewer-password-123"),
        )
        assert resp.status_code == 403

    async def test_viewer_cannot_run_script(self, test_client, real_auth_client, script_factory):
        await create_user("viewer-run", "viewer-password-123", role="viewer")
        script = await script_factory(name="viewer-run-target")

        resp = await real_auth_client.post(
            f"/api/scripts/{script.id}/run",
            headers=_basic_auth_header("viewer-run", "viewer-password-123"),
        )
        assert resp.status_code == 403

    async def test_viewer_cannot_delete_script(self, test_client, real_auth_client, script_factory):
        await create_user("viewer-delete", "viewer-password-123", role="viewer")
        script = await script_factory(name="viewer-delete-target")

        resp = await real_auth_client.delete(
            f"/api/scripts/{script.id}",
            headers=_basic_auth_header("viewer-delete", "viewer-password-123"),
        )
        assert resp.status_code == 403

    async def test_viewer_cannot_cancel_execution(
        self, test_client, real_auth_client, sample_execution
    ):
        await create_user("viewer-cancel", "viewer-password-123", role="viewer")

        resp = await real_auth_client.post(
            f"/api/executions/{sample_execution.id}/cancel",
            headers=_basic_auth_header("viewer-cancel", "viewer-password-123"),
        )
        assert resp.status_code == 403

    async def test_viewer_can_view_execution(self, test_client, real_auth_client, sample_execution):
        await create_user("viewer-view-exec", "viewer-password-123", role="viewer")

        resp = await real_auth_client.get(
            f"/api/executions/{sample_execution.id}",
            headers=_basic_auth_header("viewer-view-exec", "viewer-password-123"),
        )
        assert resp.status_code == 200

    async def test_viewer_cannot_update_settings(self, test_client, real_auth_client):
        await create_user("viewer-settings", "viewer-password-123", role="viewer")

        resp = await real_auth_client.post(
            "/api/settings/update",
            json={"theme": "dracula"},
            headers=_basic_auth_header("viewer-settings", "viewer-password-123"),
        )
        assert resp.status_code == 403

    async def test_viewer_can_read_settings(self, test_client, real_auth_client):
        await create_user("viewer-read-settings", "viewer-password-123", role="viewer")

        resp = await real_auth_client.get(
            "/api/settings",
            headers=_basic_auth_header("viewer-read-settings", "viewer-password-123"),
        )
        assert resp.status_code == 200

    async def test_viewer_cannot_list_or_create_users(self, test_client, real_auth_client):
        await create_user("viewer-users", "viewer-password-123", role="viewer")

        resp = await real_auth_client.get(
            "/api/users", headers=_basic_auth_header("viewer-users", "viewer-password-123")
        )
        assert resp.status_code == 403

        resp = await real_auth_client.post(
            "/api/users",
            json={"username": "sneaky", "password": "irrelevant123", "role": "admin"},
            headers=_basic_auth_header("viewer-users", "viewer-password-123"),
        )
        assert resp.status_code == 403


class TestAdminStillWorks:
    async def test_db_admin_can_create_and_run_scripts(self, test_client, real_auth_client):
        await create_user("real-admin", "admin-password-123", role="admin")
        auth = _basic_auth_header("real-admin", "admin-password-123")

        create_resp = await real_auth_client.post(
            "/api/scripts",
            json={"name": "admin-created", "content": "print(1)"},
            headers=auth,
        )
        assert create_resp.status_code == 201, create_resp.text

    async def test_db_admin_can_manage_users(self, test_client, real_auth_client):
        await create_user("user-admin", "admin-password-123", role="admin")

        resp = await real_auth_client.get(
            "/api/users", headers=_basic_auth_header("user-admin", "admin-password-123")
        )
        assert resp.status_code == 200
