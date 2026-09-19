"""API dependencies."""

import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import get_settings

settings = get_settings()
security = HTTPBasic()


async def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)) -> str:
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

        user = await get_user(username)
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


async def require_admin(username: str = Depends(verify_credentials)) -> str:
    """Like verify_credentials, but additionally requires the admin role.

    A username with no matching User row (the legacy env-fallback path —
    which only ADMIN_USERNAME/ADMIN_PASSWORD can authenticate as) is
    treated as admin: that account is the one F21 seeds as admin in the
    first place, and there's no "viewer" concept without a User table.
    """
    from app.services.user_service import get_user

    user = await get_user(username)
    if user is not None and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return username
