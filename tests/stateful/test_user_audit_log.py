"""P0: user-management actions (create/delete/role change/password
reset/self password change) were never audited anywhere — ScriptAuditLog
(app/models/audit_log.py) is script-specific (script_id is a NOT NULL
FK). For a system with real multi-user RBAC, "who changed whose role to
admin" or "who reset whose password" needs to be answerable.
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
    del fastapi_app.dependency_overrides[verify_credentials]
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    fastapi_app.dependency_overrides[verify_credentials] = lambda: "test_user"


async def _audit_entries(test_client, target_username=None):
    params = {"target_username": target_username} if target_username else {}
    r = await test_client.get("/api/users/audit", params=params)
    assert r.status_code == 200, r.text
    return r.json()["items"]


class TestUserAuditLog:
    async def test_create_user_is_audited(self, test_client):
        await test_client.post(
            "/api/users",
            json={"username": "audited-create", "password": "password-123456", "role": "viewer"},
        )
        entries = await _audit_entries(test_client, "audited-create")
        assert any(e["action"] == "create" for e in entries), entries

    async def test_delete_user_is_audited(self, test_client):
        r = await test_client.post(
            "/api/users",
            json={"username": "audited-delete", "password": "password-123456", "role": "viewer"},
        )
        user_id = r.json()["id"]
        await test_client.delete(f"/api/users/{user_id}")
        entries = await _audit_entries(test_client, "audited-delete")
        assert any(e["action"] == "delete" for e in entries), entries

    async def test_role_change_is_audited_with_before_after(self, test_client):
        r = await test_client.post(
            "/api/users",
            json={"username": "audited-role", "password": "password-123456", "role": "viewer"},
        )
        user_id = r.json()["id"]
        await test_client.patch(f"/api/users/{user_id}", json={"role": "admin"})
        entries = await _audit_entries(test_client, "audited-role")
        role_entries = [e for e in entries if e["action"] == "role_change"]
        assert len(role_entries) == 1, entries
        assert role_entries[0]["detail"] == "viewer -> admin"

    async def test_admin_password_reset_is_audited_without_leaking_password(self, test_client):
        r = await test_client.post(
            "/api/users",
            json={"username": "audited-reset", "password": "password-123456", "role": "viewer"},
        )
        user_id = r.json()["id"]
        await test_client.patch(f"/api/users/{user_id}", json={"password": "brand-new-password-2"})
        entries = await _audit_entries(test_client, "audited-reset")
        reset_entries = [e for e in entries if e["action"] == "password_reset"]
        assert len(reset_entries) == 1, entries
        assert "brand-new-password-2" not in (reset_entries[0]["detail"] or "")

    async def test_self_password_change_is_audited(self, test_client, real_auth_client):
        from app.config import get_settings

        await create_user("self-audit-user", "original-password-1", role="viewer")
        await real_auth_client.post(
            "/api/users/me/password",
            json={"current_password": "original-password-1", "new_password": "brand-new-password-2"},
            headers=_basic_auth_header("self-audit-user", "original-password-1"),
        )
        # test_client's own baked Authorization header stops working once
        # real_auth_client removed the verify_credentials override (it's a
        # single global override on the shared app) — query through
        # real_auth_client with real admin credentials instead.
        settings = get_settings()
        r = await real_auth_client.get(
            "/api/users/audit",
            params={"target_username": "self-audit-user"},
            headers=_basic_auth_header(settings.admin_username, settings.admin_password),
        )
        assert r.status_code == 200, r.text
        entries = r.json()["items"]
        self_entries = [e for e in entries if e["action"] == "self_password_change"]
        assert len(self_entries) == 1, entries
        assert self_entries[0]["changed_by"] == "self-audit-user"

    async def test_audit_log_respects_limit(self, test_client):
        for i in range(5):
            await test_client.post(
                "/api/users",
                json={"username": f"limit-test-{i}", "password": "password-123456", "role": "viewer"},
            )
        r = await test_client.get("/api/users/audit", params={"limit": 2})
        assert r.status_code == 200
        assert len(r.json()["items"]) == 2

    async def test_audit_log_requires_admin(self, test_client, real_auth_client):
        await create_user("audit-viewer", "viewer-password-123", role="viewer")
        r = await real_auth_client.get(
            "/api/users/audit", headers=_basic_auth_header("audit-viewer", "viewer-password-123")
        )
        assert r.status_code == 403
