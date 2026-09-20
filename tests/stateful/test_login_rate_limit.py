"""P0: brute-force protection on Basic Auth login. Before this, failed
login attempts against verify_credentials (app/api/dependencies.py) were
never rate-limited — only expensive script operations were
(app/api/rate_limit.py). An attacker could brute-force a password with
no throttling at all.
"""

import base64

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import verify_credentials
from app.api.rate_limit import clear_rate_limits
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
    clear_rate_limits()


class TestLoginLockout:
    async def test_repeated_failed_logins_get_locked_out(self, test_client, real_auth_client):
        await create_user("lockout-target", "correct-password-123", role="viewer")
        bad_auth = _basic_auth_header("lockout-target", "wrong-password")

        statuses = []
        for _ in range(15):
            r = await real_auth_client.get("/api/scripts", headers=bad_auth)
            statuses.append(r.status_code)

        assert 401 in statuses
        assert 429 in statuses, f"never got locked out: {statuses}"
        # once locked out, even the CORRECT password is rejected until the window expires
        good_auth = _basic_auth_header("lockout-target", "correct-password-123")
        r = await real_auth_client.get("/api/scripts", headers=good_auth)
        assert r.status_code == 429

    async def test_successful_logins_are_not_rate_limited(self, test_client, real_auth_client):
        await create_user("good-login-user", "correct-password-123", role="viewer")
        good_auth = _basic_auth_header("good-login-user", "correct-password-123")

        for _ in range(15):
            r = await real_auth_client.get("/api/scripts", headers=good_auth)
            assert r.status_code == 200

    async def test_lockout_is_per_username_not_global(self, test_client, real_auth_client):
        """A lockout on one username must not block a different, unrelated
        username from the same client."""
        await create_user("victim-a", "password-aaaaaaaa", role="viewer")
        await create_user("victim-b", "password-bbbbbbbb", role="viewer")

        bad_auth_a = _basic_auth_header("victim-a", "wrong-password")
        for _ in range(15):
            await real_auth_client.get("/api/scripts", headers=bad_auth_a)

        good_auth_b = _basic_auth_header("victim-b", "password-bbbbbbbb")
        r = await real_auth_client.get("/api/scripts", headers=good_auth_b)
        assert r.status_code == 200
