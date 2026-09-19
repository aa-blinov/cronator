"""verify_credentials() gates every API endpoint and the whole UI — it had
28% coverage (only the "happy path via test_client's dependency override"
was ever exercised, which bypasses this function entirely). These call it
directly to pin down the real auth decision tree: DB-backed users take
priority over the env-defined admin, a DB user with a wrong password is
rejected outright (no fallback to the env admin, even if that password
would've matched), and a DB lookup failure (missing table, etc.) falls
through to the env admin rather than locking everyone out.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPBasicCredentials

from app.api.dependencies import verify_credentials


def _creds(username: str, password: str) -> HTTPBasicCredentials:
    return HTTPBasicCredentials(username=username, password=password)


@pytest.mark.asyncio
async def test_db_user_with_correct_password_is_accepted():
    fake_user = MagicMock(password_hash="pbkdf2_sha256$...")
    with (
        patch("app.services.user_service.get_user", AsyncMock(return_value=fake_user)),
        patch("app.services.user_service.verify_password", return_value=True),
    ):
        result = await verify_credentials(_creds("alice", "correct-password"))
    assert result == "alice"


@pytest.mark.asyncio
async def test_db_user_with_wrong_password_is_rejected_outright():
    """A DB user overrides the env-admin fallback entirely once that
    username exists — it must NOT fall through and succeed even if the
    submitted password happens to match the env admin's password."""
    fake_user = MagicMock(password_hash="pbkdf2_sha256$...")
    with (
        patch("app.services.user_service.get_user", AsyncMock(return_value=fake_user)),
        patch("app.services.user_service.verify_password", return_value=False),
        patch("app.api.dependencies.settings") as mock_settings,
    ):
        mock_settings.admin_username = "alice"
        mock_settings.admin_password = "wrong-password-guess"
        with pytest.raises(HTTPException) as exc_info:
            await verify_credentials(_creds("alice", "wrong-password-guess"))
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_falls_back_to_env_admin_when_username_not_in_db():
    with (
        patch("app.services.user_service.get_user", AsyncMock(return_value=None)),
        patch("app.api.dependencies.settings") as mock_settings,
    ):
        mock_settings.admin_username = "admin"
        mock_settings.admin_password = "s3cret"
        result = await verify_credentials(_creds("admin", "s3cret"))
    assert result == "admin"


@pytest.mark.asyncio
async def test_env_admin_wrong_password_is_rejected():
    with (
        patch("app.services.user_service.get_user", AsyncMock(return_value=None)),
        patch("app.api.dependencies.settings") as mock_settings,
    ):
        mock_settings.admin_username = "admin"
        mock_settings.admin_password = "s3cret"
        with pytest.raises(HTTPException) as exc_info:
            await verify_credentials(_creds("admin", "not-s3cret"))
    assert exc_info.value.status_code == 401
    assert exc_info.value.headers == {"WWW-Authenticate": "Basic"}


@pytest.mark.asyncio
async def test_env_admin_wrong_username_is_rejected():
    with (
        patch("app.services.user_service.get_user", AsyncMock(return_value=None)),
        patch("app.api.dependencies.settings") as mock_settings,
    ):
        mock_settings.admin_username = "admin"
        mock_settings.admin_password = "s3cret"
        with pytest.raises(HTTPException) as exc_info:
            await verify_credentials(_creds("not-admin", "s3cret"))
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_db_lookup_failure_falls_through_to_env_admin():
    """A missing users table (fresh install, pre-migration) or any other DB
    error during the lookup must not lock every admin out — it should fall
    through to the env-defined credentials rather than raising."""
    with (
        patch(
            "app.services.user_service.get_user",
            AsyncMock(side_effect=RuntimeError("no such table: users")),
        ),
        patch("app.api.dependencies.settings") as mock_settings,
    ):
        mock_settings.admin_username = "admin"
        mock_settings.admin_password = "s3cret"
        result = await verify_credentials(_creds("admin", "s3cret"))
    assert result == "admin"


@pytest.mark.asyncio
async def test_rejects_when_neither_db_user_nor_env_admin_match():
    with (
        patch("app.services.user_service.get_user", AsyncMock(return_value=None)),
        patch("app.api.dependencies.settings") as mock_settings,
    ):
        mock_settings.admin_username = "admin"
        mock_settings.admin_password = "s3cret"
        with pytest.raises(HTTPException) as exc_info:
            await verify_credentials(_creds("nobody", "nothing"))
    assert exc_info.value.status_code == 401
