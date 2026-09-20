"""Tests for the gap fixed after the F21 RBAC audit: admins couldn't
change an existing user's password/role (only create/delete), and no
one could change their own password without editing .env and
restarting. Covers PATCH /api/users/{id} and POST /api/users/me/password,
plus the last-admin-demotion guard mirroring the existing
last-admin-deletion guard.
"""

import base64

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import verify_credentials
from app.main import app as fastapi_app
from app.services.user_service import create_user, get_user, verify_password

pytestmark = pytest.mark.asyncio


def _basic_auth_header(username: str, password: str) -> dict:
    token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
async def real_auth_client(test_client):
    del fastapi_app.dependency_overrides[verify_credentials]
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    fastapi_app.dependency_overrides[verify_credentials] = lambda: "test_user"


class TestAdminResetsAnotherUser:
    async def test_admin_can_reset_password(self, test_client):
        user = await create_user("reset-target", "old-password-123", role="viewer")

        r = await test_client.patch(
            f"/api/users/{user.id}", json={"password": "new-password-456"}
        )
        assert r.status_code == 200, r.text

        refreshed = await get_user("reset-target")
        assert verify_password("new-password-456", refreshed.password_hash) is True
        assert verify_password("old-password-123", refreshed.password_hash) is False

    async def test_admin_can_change_role(self, test_client):
        user = await create_user("role-target", "password-123456", role="viewer")

        r = await test_client.patch(f"/api/users/{user.id}", json={"role": "admin"})
        assert r.status_code == 200, r.text
        assert r.json()["role"] == "admin"

    async def test_empty_patch_rejected(self, test_client):
        user = await create_user("empty-patch-target", "password-123456", role="viewer")
        r = await test_client.patch(f"/api/users/{user.id}", json={})
        assert r.status_code == 400

    async def test_unknown_user_404(self, test_client):
        r = await test_client.patch("/api/users/999999", json={"password": "whatever-1234"})
        assert r.status_code == 404

    async def test_cannot_demote_last_admin(self, test_client):
        from app.services.user_service import list_users

        users = await list_users()
        admins = [u for u in users if u.role == "admin"]
        assert len(admins) == 1, "test assumes exactly one seeded admin"

        r = await test_client.patch(f"/api/users/{admins[0].id}", json={"role": "viewer"})
        assert r.status_code == 400

    async def test_demoting_admin_is_fine_when_another_admin_exists(self, test_client):
        target = await create_user("second-admin", "password-123456", role="admin")

        r = await test_client.patch(f"/api/users/{target.id}", json={"role": "viewer"})
        assert r.status_code == 200, r.text


class TestSelfServicePasswordChange:
    async def test_user_can_change_own_password(self, test_client, real_auth_client):
        await create_user("self-changer", "original-password-1", role="viewer")

        r = await real_auth_client.post(
            "/api/users/me/password",
            json={"current_password": "original-password-1", "new_password": "brand-new-password-2"},
            headers=_basic_auth_header("self-changer", "original-password-1"),
        )
        assert r.status_code == 204, r.text

        user = await get_user("self-changer")
        assert verify_password("brand-new-password-2", user.password_hash) is True

    async def test_wrong_current_password_rejected(self, test_client, real_auth_client):
        await create_user("self-changer-2", "original-password-1", role="viewer")

        r = await real_auth_client.post(
            "/api/users/me/password",
            json={"current_password": "totally-wrong-pw", "new_password": "brand-new-password-2"},
            headers=_basic_auth_header("self-changer-2", "original-password-1"),
        )
        assert r.status_code == 401

        user = await get_user("self-changer-2")
        assert verify_password("original-password-1", user.password_hash) is True

    async def test_env_fallback_account_gets_clear_error(self, test_client, real_auth_client):
        from app.config import get_settings

        settings = get_settings()
        r = await real_auth_client.post(
            "/api/users/me/password",
            json={"current_password": settings.admin_password, "new_password": "brand-new-password-2"},
            headers=_basic_auth_header(settings.admin_username, settings.admin_password),
        )
        # Only reaches the env-fallback branch if this username has no User
        # row; if F21 seeding already created one, it behaves like a normal
        # user and that's fine too — either way it must not 500.
        assert r.status_code in (204, 400)


class TestUsersPage:
    async def test_admin_sees_users_page(self, test_client):
        r = await test_client.get("/users")
        assert r.status_code == 200
        assert "Users" in r.text

    async def test_viewer_gets_403_on_users_page(self, test_client, real_auth_client):
        await create_user("page-viewer", "viewer-password-123", role="viewer")

        r = await real_auth_client.get(
            "/users", headers=_basic_auth_header("page-viewer", "viewer-password-123")
        )
        assert r.status_code == 403
