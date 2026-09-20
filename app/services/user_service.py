"""User service: hashing, verification, creation, listing for F21."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime

from sqlalchemy import select

from app.database import async_session_maker
from app.models.user import User
from app.models.user_audit_log import UserAuditLog

# PBKDF2-HMAC-SHA256 with 200_000 iterations and a 32-byte salt.
ITERATIONS = 200_000
SALT_BYTES = 32
DKLEN = 32


def hash_password(password: str) -> str:
    """Hash a password using PBKDF2-HMAC-SHA256."""
    salt = secrets.token_bytes(SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS, dklen=DKLEN)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time verify a password against the stored hash."""
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iters_i = int(iters)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iters_i, dklen=len(expected)
        )
        return hmac.compare_digest(candidate, expected)
    except Exception:
        return False


async def get_user(username: str) -> User | None:
    async with async_session_maker() as db:
        result = await db.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()


async def list_users() -> list[User]:
    async with async_session_maker() as db:
        result = await db.execute(select(User).order_by(User.created_at))
        return list(result.scalars().all())


async def create_user(username: str, password: str, role: str = "viewer") -> User:
    if role not in ("admin", "viewer"):
        raise ValueError(f"invalid role {role!r}")
    user = User(
        username=username,
        password_hash=hash_password(password),
        role=role,
        created_at=datetime.now(UTC),
    )
    async with async_session_maker() as db:
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


async def update_user(
    user_id: int, password: str | None = None, role: str | None = None
) -> User | None:
    if role is not None and role not in ("admin", "viewer"):
        raise ValueError(f"invalid role {role!r}")
    async with async_session_maker() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            return None
        if password is not None:
            user.password_hash = hash_password(password)
        if role is not None:
            user.role = role
        await db.commit()
        await db.refresh(user)
        return user


async def delete_user(user_id: int) -> bool:
    async with async_session_maker() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            return False
        await db.delete(user)
        await db.commit()
        return True


async def count_admins() -> int:
    async with async_session_maker() as db:
        result = await db.execute(select(User).where(User.role == "admin"))
        return len(list(result.scalars().all()))


async def record_user_audit(
    target_username: str, action: str, changed_by: str, detail: str | None = None
) -> None:
    entry = UserAuditLog(
        target_username=target_username,
        action=action,
        detail=detail,
        changed_by=changed_by,
        changed_at=datetime.now(UTC),
    )
    async with async_session_maker() as db:
        db.add(entry)
        await db.commit()


async def list_user_audit(
    target_username: str | None = None, limit: int = 200
) -> list[UserAuditLog]:
    async with async_session_maker() as db:
        stmt = select(UserAuditLog).order_by(
            UserAuditLog.changed_at.desc(), UserAuditLog.id.desc()
        )
        if target_username is not None:
            stmt = stmt.where(UserAuditLog.target_username == target_username)
        stmt = stmt.limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())


async def ensure_admin_seeded() -> None:
    """Ensure at least one admin user exists. Seed from env vars if no users yet."""
    from app.config import get_settings

    settings = get_settings()
    existing = await list_users()
    if existing:
        return

    # No users in DB — seed from env
    admin_username = settings.admin_username
    admin_password = settings.admin_password
    if not admin_username or not admin_password:
        return
    await create_user(admin_username, admin_password, role="admin")
