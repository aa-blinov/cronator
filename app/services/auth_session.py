"""Login-session lifecycle: issue, validate, revoke.

The rules of the road:
- The cookie value is the only thing the client ever sees; the database
  stores its SHA-256, so a leaked database dump is not a session kit.
- Expiry is enforced on read (the job that purges expired rows runs on a
  best-effort schedule; nothing should trust the absence of a sweeper).
- Revocation (logout) deletes the row — a stolen cookie stops working
  the moment the user notices, which is the whole point of server-side
  sessions over forever-cookies.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete as sa_delete
from sqlalchemy import select

from app.models.auth_session import AuthSession

logger = logging.getLogger(__name__)

# How long a login stays valid. A week is the usual back-office trade:
# re-login daily would be security theatre against a host that already
# runs the browser, forever would defeat the logout.
SESSION_TTL = timedelta(days=7)


def hash_token(token: str) -> str:
    """The cookie stores a random token; the DB stores only its hash."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _as_utc(dt: datetime) -> datetime:
    """SQLite returns naive datetimes (UTC by convention in this app);
    PostgreSQL returns tz-aware ones. Compare like with like."""
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


async def create_session(username: str) -> str:
    """Issue a session; returns the token to hand to the client's cookie."""
    from app.database import async_session_maker

    token = secrets.token_urlsafe(32)
    async with async_session_maker() as db:
        db.add(
            AuthSession(  # type: ignore[call-arg]
                username=username,
                token_hash=hash_token(token),
                expires_at=datetime.now(UTC) + SESSION_TTL,
            )
        )
        await db.commit()
    return token


async def validate_session(token: str) -> str | None:
    """The username the token belongs to, or None (unknown/expired)."""
    from app.database import async_session_maker

    if not token:
        return None
    async with async_session_maker() as db:
        row = (
            await db.execute(
                select(AuthSession).where(AuthSession.token_hash == hash_token(token))
            )
        ).scalar_one_or_none()
        if row is None or _as_utc(row.expires_at) <= datetime.now(UTC):
            return None
        return row.username


async def delete_session(token: str) -> None:
    """Revoke one session (logout). Missing rows are fine: idempotent."""
    from app.database import async_session_maker

    async with async_session_maker() as db:
        await db.execute(
            sa_delete(AuthSession).where(AuthSession.token_hash == hash_token(token))
        )
        await db.commit()


async def purge_expired() -> int:
    """Drop expired rows; returns how many. Best-effort housekeeping."""
    from app.database import async_session_maker

    async with async_session_maker() as db:
        result = await db.execute(
            sa_delete(AuthSession).where(
                AuthSession.expires_at < datetime.now(UTC).replace(tzinfo=None)
            )
        )
        await db.commit()
        return result.rowcount or 0
