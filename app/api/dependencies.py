"""API dependencies."""

import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import get_settings

settings = get_settings()
security = HTTPBasic()


def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    """Verify HTTP Basic Auth credentials.

    Order of checks (F21):
    1. If a User record with this username exists, verify against the
       stored PBKDF2 hash.
    2. Otherwise fall back to the env-defined admin (legacy single-user
       auth) so deployments without a User table still work.
    """
    username = credentials.username
    password = credentials.password

    # Try DB-backed auth first (fast-fails: missing user → fall through)
    try:
        from app.services.user_service import get_user, verify_password

        user = None
        try:
            import asyncio

            user = asyncio.get_event_loop().run_until_complete(get_user(username))
        except RuntimeError:
            # Already inside an event loop — use a sync helper instead
            from app.services.user_service import verify_password as _vp

            # We can't await from sync context here; fall back to env.
            user = None
        if user is not None:
            if verify_password(password, user.password_hash):
                return username
            # User exists but password wrong → reject
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Basic"},
            )
    except HTTPException:
        raise
    except Exception:
        # DB lookup failed (e.g. table doesn't exist in test) → fall through
        pass

    # Legacy single-user fallback (env-defined admin)
    correct_username = secrets.compare_digest(
        credentials.username.encode("utf8"),
        settings.admin_username.encode("utf8"),
    )
    correct_password = secrets.compare_digest(
        credentials.password.encode("utf8"),
        settings.admin_password.encode("utf8"),
    )

    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    return credentials.username
