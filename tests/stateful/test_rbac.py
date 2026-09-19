"""TDD tests for F21: Multi-user RBAC.

- A `User` table with id, username, password_hash, role
- An `admin` role and a `viewer` role
- Auth verifies username/password against the User table (not just env vars)
- /api/users endpoints for admin to create/list users
- Default admin user seeded from ADMIN_USERNAME/ADMIN_PASSWORD env if no users exist

Every mutating endpoint across scripts/executions/settings/users/pages
requires admin (via require_admin in app/api/dependencies.py); viewers get
read-only access everywhere. These tests use the test_client fixture's
blanket verify_credentials override, which always resolves as admin — see
tests/stateful/test_rbac_enforcement.py for tests that authenticate as a
real DB-backed viewer/admin user and actually exercise role gating.
"""

import pytest


@pytest.mark.asyncio
async def test_users_endpoint_requires_admin(test_client):
    """GET /api/users must require authentication."""
    r = await test_client.get("/api/users")
    assert r.status_code == 200  # authenticated via test fixture


@pytest.mark.asyncio
async def test_users_list_seeded_admin(test_client):
    """After seeding, GET /api/users returns at least the admin user."""
    r = await test_client.get("/api/users")
    assert r.status_code == 200
    body = r.json()
    users = body.get("items", body) if isinstance(body, dict) else body
    assert isinstance(users, list)
    assert any(u.get("role") == "admin" for u in users), users


@pytest.mark.asyncio
async def test_create_user_as_admin(test_client):
    """Admin can create a new user."""
    import time

    username = f"viewer_{int(time.time())}"
    r = await test_client.post(
        "/api/users",
        json={"username": username, "password": "test-password-1234", "role": "viewer"},
    )
    assert r.status_code in (200, 201), r.text


@pytest.mark.asyncio
async def test_user_cannot_be_created_with_short_password(test_client):
    """Password must be at least 8 characters."""
    r = await test_client.post(
        "/api/users",
        json={"username": "short_pw", "password": "short", "role": "viewer"},
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_user_login_works(test_client):
    """A created user can be verified by verify_password against their stored hash."""
    import time

    from app.services.user_service import get_user, verify_password

    username = f"loginuser_{int(time.time())}"
    pw = "test-password-1234"
    r = await test_client.post(
        "/api/users",
        json={"username": username, "password": pw, "role": "viewer"},
    )
    assert r.status_code in (200, 201), r.text

    # The DB-stored password_hash must verify against the plaintext password
    user = await get_user(username)
    assert user is not None
    assert verify_password(pw, user.password_hash) is True
    # And wrong passwords must NOT verify
    assert verify_password("wrong-password-1234", user.password_hash) is False
