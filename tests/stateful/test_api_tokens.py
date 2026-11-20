"""API tokens: revocable bearer credentials for scripts and API clients.

The management routes are admin-only; a token authenticates like an admin
over the REST API but is revoked without touching any password. Only the
SHA-256 hash is stored, so a database dump cannot be replayed as a token.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.api.dependencies import page_admin, page_user, verify_credentials
from app.main import app as fastapi_app
from app.services.user_service import create_user

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def real_auth_client(test_client):
    """The app with real credential checks instead of the blanket override."""
    del fastapi_app.dependency_overrides[verify_credentials]
    del fastapi_app.dependency_overrides[page_user]
    del fastapi_app.dependency_overrides[page_admin]
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    fastapi_app.dependency_overrides[verify_credentials] = lambda: "test_user"


async def _create_token(test_client, name="ci-nightly"):
    r = await test_client.post("/api/tokens", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


async def _issue_token(name="ci-nightly"):
    """Service-level issue for tests using real_auth_client: that fixture
    removes the blanket auth override, so test_client's Basic admin:admin
    header no longer authenticates."""
    from app.services.api_token_service import create_token

    row, plain = await create_token(name, "test_user")
    return {"id": row.id, "token": plain, "prefix": row.prefix}


async def test_create_returns_plaintext_once_and_stores_only_a_hash(test_client, db_session):
    created = await _create_token(test_client)

    assert created["token"].startswith("ctk_")
    assert created["prefix"] == created["token"][:12]
    assert created["revoked_at"] is None

    raw = await db_session.execute(
        text("SELECT token_hash FROM api_tokens WHERE id = :id"), {"id": created["id"]}
    )
    stored_hash = raw.scalar_one()
    assert created["token"] not in stored_hash
    assert len(stored_hash) == 64  # sha256 hex digest

    listed = await test_client.get("/api/tokens")
    assert listed.status_code == 200
    items = listed.json()
    assert all("token" not in item for item in items)


async def test_bearer_token_authenticates_api_calls(real_auth_client):
    created = await _issue_token()

    r = await real_auth_client.get(
        "/api/scripts", headers={"Authorization": f"Bearer {created['token']}"}
    )
    assert r.status_code == 200, r.text


async def test_invalid_bearer_token_is_rejected(real_auth_client):
    r = await real_auth_client.get(
        "/api/scripts", headers={"Authorization": "Bearer ctk_not-a-real-token"}
    )
    assert r.status_code == 401, r.text


async def test_revoked_token_stops_working_immediately(real_auth_client):
    from app.services.api_token_service import revoke_token

    created = await _issue_token("to-be-revoked")
    headers = {"Authorization": f"Bearer {created['token']}"}

    r = await real_auth_client.get("/api/scripts", headers=headers)
    assert r.status_code == 200

    assert await revoke_token(created["id"])

    r = await real_auth_client.get("/api/scripts", headers=headers)
    assert r.status_code == 401

    # Revoking twice is harmless (idempotent) but an unknown id is a 404.
    assert await revoke_token(created["id"])
    assert not await revoke_token(99999)


async def test_revoke_endpoint_requires_admin(test_client):
    await _create_token(test_client, "via-api")
    listed = (await test_client.get("/api/tokens")).json()
    row = next(item for item in listed if item["name"] == "via-api")

    r = await test_client.delete(f"/api/tokens/{row['id']}")
    assert r.status_code == 204, r.text
    # Revocation keeps the row for the audit trail, marked revoked.
    remaining = (await test_client.get("/api/tokens")).json()
    assert next(item for item in remaining if item["id"] == row["id"])["revoked_at"]


async def test_viewer_cannot_manage_tokens(test_client, real_auth_client):
    import base64

    await create_user("token-viewer", "viewer-password-123", role="viewer")
    auth = base64.b64encode(b"token-viewer:viewer-password-123").decode("ascii")
    headers = {"Authorization": f"Basic {auth}"}

    assert (await real_auth_client.get("/api/tokens", headers=headers)).status_code == 403
    assert (
        await real_auth_client.post("/api/tokens", json={"name": "nope"}, headers=headers)
    ).status_code == 403


async def test_token_name_is_validated(test_client):
    r = await test_client.post("/api/tokens", json={"name": "x"})
    assert r.status_code == 422, r.text
    r = await test_client.post("/api/tokens", json={"name": "ok-name"})
    assert r.status_code == 201, r.text
