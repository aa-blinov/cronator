"""The cookie login flow: /login, /logout, session lifecycle.

The page-level auth (page_user) redirects to /login instead of the Basic
Auth popup — that redirect, the cookie hand-out and the server-side
revocation are what these tests pin down.
"""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import auth_session
from app.services.user_service import create_user


@pytest_asyncio.fixture(autouse=True)
def _standalone_session_maker(test_engine, monkeypatch):
    """The session-lifecycle tests run outside test_client's DB wiring, so
    they must point the service-level session makers at this test's own
    engine — without it the first test would write into the live dev
    database instead of the test one."""
    from sqlalchemy.ext.asyncio import async_sessionmaker as _mk

    import app.services.user_service as _us
    from app.services.user_service import async_session_maker as _unused  # noqa: F401

    maker = _mk(test_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(
        "app.database.async_session_maker", maker
    )
    monkeypatch.setattr(_us, "async_session_maker", maker)
    yield maker


class TestSessionService:
    async def test_create_and_validate(self, db_session):
        await create_user("session-user", "session-password-123")
        token = await auth_session.create_session("session-user")
        assert await auth_session.validate_session(token) == "session-user"

    async def test_unknown_token_is_nobody(self, db_session):
        assert await auth_session.validate_session("not-a-real-token") is None
        assert await auth_session.validate_session("") is None

    async def test_delete_revokes(self, db_session):
        await create_user("revoke-user", "revoke-password-123")
        token = await auth_session.create_session("revoke-user")
        assert await auth_session.validate_session(token) == "revoke-user"
        await auth_session.delete_session(token)
        assert await auth_session.validate_session(token) is None
        # second delete is fine (logout twice, a stale tab, …)
        await auth_session.delete_session(token)

    async def test_expired_session_is_nobody(self, db_session, monkeypatch):
        await create_user("expired-user", "expired-password-123")
        token = await auth_session.create_session("expired-user")
        from sqlalchemy import update

        from app.database import async_session_maker

        # Age the row past its expiry directly; the read is what must
        # enforce the date (the sweeper is best-effort).
        async with async_session_maker() as db:
            await db.execute(
                update(auth_session.AuthSession)
                .where(auth_session.AuthSession.token_hash == auth_session.hash_token(token))
                .values(expires_at=datetime.now(UTC) - timedelta(days=1))
            )
            await db.commit()
        assert await auth_session.validate_session(token) is None

    async def test_purge_expired_only(self, db_session):
        await create_user("purge-user", "purge-password-123")
        keep = await auth_session.create_session("purge-user")
        dead = await auth_session.create_session("purge-user")
        from sqlalchemy import update

        from app.database import async_session_maker

        async with async_session_maker() as db:
            await db.execute(
                update(auth_session.AuthSession)
                .where(auth_session.AuthSession.token_hash == auth_session.hash_token(dead))
                .values(expires_at=datetime.now(UTC) - timedelta(days=1))
            )
            await db.commit()
        purged = await auth_session.purge_expired()
        assert purged >= 1
        assert await auth_session.validate_session(keep) == "purge-user"
        assert await auth_session.validate_session(dead) is None

    def test_hash_is_not_the_token(self):
        token = "some-token"
        h = auth_session.hash_token(token)
        assert h != token
        assert len(h) == 64


class TestLoginFlow:
    @pytest.fixture
    async def real_auth_client(self, test_client):
        """Like test_client, but with real auth: no blanket override.

        Deletes the page-level overrides too — that is the whole point:
        this client sees exactly what an anonymous browser sees."""
        from app.api.dependencies import page_admin, page_user
        from app.main import app as fastapi_app

        del fastapi_app.dependency_overrides[page_user]
        del fastapi_app.dependency_overrides[page_admin]
        # test_client's default Basic header would authenticate the
        # request before the redirect logic ever runs; this test needs
        # the anonymous visitor exactly.
        test_client.headers.pop("authorization", None)
        yield test_client
        # test_client's teardown clears everything anyway.

    async def test_anonymous_page_redirects_to_login(self, real_auth_client):
        # No session cookie, no Basic header: the page must send the
        # browser to /login, not to a Basic popup (401) and not leak the
        # page.
        r = await real_auth_client.get("/scripts", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"].startswith("/login")

    async def test_login_page_renders(self, test_client):
        r = await test_client.get("/login")
        assert r.status_code == 200
        assert "Sign in" in r.text

    async def test_wrong_password_shows_error(self, test_client):
        r = await test_client.post("/login", data={"username": "admin", "password": "wrong"})
        assert r.status_code == 200
        assert "Invalid username or password" in r.text

    async def test_login_sets_cookie_and_lands(self, test_client):
        r = await test_client.post(
            "/login",
            data={"username": "admin", "password": "admin"},
            follow_redirects=False,
        )
        # The env admin (admin/admin in the test env) or a seeded user —
        # both must authenticate and get the session cookie.
        if r.status_code == 200:
            assert "Invalid username or password" in r.text
            return
        assert r.status_code == 303
        assert any(
            c.name == "cronator_session" for c in r.cookies.jar
        ), "login must set the session cookie"

    async def test_logout_clears_server_side(self, test_client):
        await create_user("logout-user", "logout-password-123")
        token = await auth_session.create_session("logout-user")
        test_client.cookies.set("cronator_session", token)

        r = await test_client.post("/logout", follow_redirects=False)
        assert r.status_code == 303
        assert await auth_session.validate_session(token) is None
