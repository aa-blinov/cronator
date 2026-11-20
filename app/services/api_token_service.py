"""API tokens: revocable credentials for scripts and API clients.

Basic Auth means handing an automation the admin password. Tokens carry no
reusable password: only the SHA-256 hash is stored, so a database dump is
not a token kit (same rule as login sessions). A token acts with admin
rights over the API — the deployment is one trusted team, not a
multi-tenant service — but it can be revoked without touching anyone's
password.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime

from sqlalchemy import select

from app.database import async_session_maker
from app.models.api_token import ApiToken

TOKEN_PREFIX = "ctk_"
TOKEN_BYTES = 32


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_token(name: str, created_by: str) -> tuple[ApiToken, str]:
    """Create a token. The plaintext is returned once and never stored."""
    plain = TOKEN_PREFIX + secrets.token_urlsafe(TOKEN_BYTES)
    async with async_session_maker() as db:
        row = ApiToken(
            name=name,
            token_hash=_hash(plain),
            prefix=plain[:12],
            created_by=created_by,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row, plain


async def verify_token(plain: str) -> str | None:
    """Return the actor string for a valid token, or None.

    Revoked and unknown tokens are indistinguishable to the caller — no
    oracle for token existence. last_used_at is written on each success.
    """
    if not plain.startswith(TOKEN_PREFIX):
        return None

    token_hash = _hash(plain)
    async with async_session_maker() as db:
        result = await db.execute(
            select(ApiToken).where(
                ApiToken.token_hash == token_hash,
                ApiToken.revoked_at.is_(None),
            )
        )
        token = result.scalar_one_or_none()
        if token is None:
            return None

        token.last_used_at = datetime.now(UTC)
        await db.commit()
        return f"api-token:{token.name}"


async def list_tokens() -> list[ApiToken]:
    """All tokens, active and revoked, newest first."""
    async with async_session_maker() as db:
        result = await db.execute(select(ApiToken).order_by(ApiToken.created_at.desc()))
        return list(result.scalars().all())


async def revoke_token(token_id: int) -> bool:
    """Revoke a token by id. Returns False when the id does not exist."""
    async with async_session_maker() as db:
        token = await db.get(ApiToken, token_id)
        if token is None:
            return False
        if token.revoked_at is None:
            token.revoked_at = datetime.now(UTC)
            await db.commit()
        return True
