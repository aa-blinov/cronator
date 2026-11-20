"""API dependencies."""

import secrets

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.api.rate_limit import check_login_lockout, record_login_failure
from app.config import get_settings

settings = get_settings()
security = HTTPBasic()
# The HTML pages authenticate through a login session cookie, falling
# back to Basic Auth for API clients (curl, scripts, old bookmarks with
# stored passwords). auto_error=False is what makes the layering
# possible: without it, a browser showing the page would get the Basic
# popup again before the cookie ever had a chance.
security_optional = HTTPBasic(auto_error=False)


async def check_credentials(username: str, password: str) -> None:
    """Validate one username/password pair; raise 401 on failure.

    The single place both the login form and the Basic Auth path go
    through, so brute-force protection and the user-vs-env fallback can
    never drift apart.
    """
    check_login_lockout(username)

    # Try DB-backed auth first (fast-fails: missing user → fall through)
    try:
        from app.services.user_service import get_user, verify_password

        user = await get_user(username)
        if user is not None:
            if verify_password(password, user.password_hash):
                return
            # User exists but password wrong → reject
            record_login_failure(username)
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
        username.encode("utf8"),
        settings.admin_username.encode("utf8"),
    )
    correct_password = secrets.compare_digest(
        password.encode("utf8"),
        settings.admin_password.encode("utf8"),
    )

    if not (correct_username and correct_password):
        record_login_failure(username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


async def verify_credentials(
    credentials: HTTPBasicCredentials | None = Depends(security_optional),
    request: Request = None,  # default keeps direct stateless-test calls valid
) -> str:
    """Verify the API credentials: a Bearer token or HTTP Basic Auth.

    Basic Auth remains for scripts and API clients; a Bearer token is the
    revocable alternative that lets automation avoid carrying the admin
    password. Tokens are hashed at rest and carry admin rights over the
    API, like the env-defined admin account.

    The request parameter has a default so stateless tests can still call
    this directly with just a credentials object; FastAPI injects it from
    the annotation on real requests.
    """
    if request is not None:
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            from app.services.api_token_service import verify_token

            actor = await verify_token(header[7:].strip())
            if actor is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid API token",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return actor

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Basic"},
        )

    await check_credentials(credentials.username, credentials.password)
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


SESSION_COOKIE_NAME = "cronator_session"


class RoutingToLogin(HTTPException):
    """A 303 carrying the login location — FastAPI's handler renders it."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_303_SEE_OTHER,
            detail="Redirecting to login",
            headers={"Location": "/login"},
        )


async def page_user(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(security_optional),
) -> str:
    """Authenticate an HTML page visit; redirect to /login instead of the
    Basic popup.

    A valid session cookie wins (that is the login flow's own artifact);
    a Basic header still works for API-style tooling pointed at an HTML
    route; with neither the browser gets a 303 to the login page — the
    reason this must raise RoutingToLogin instead of the plain 401 of
    verify_credentials (the popup).
    """
    from app.services.auth_session import validate_session

    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if session_token:
        username = await validate_session(session_token)
        if username:
            return username

    if credentials is not None:
        await check_credentials(credentials.username, credentials.password)
        return credentials.username

    raise RoutingToLogin()


async def page_admin(username: str = Depends(page_user)) -> str:
    """The HTML equivalent of require_admin: admins only, others land on
    their own pages (a 403 page for a known viewer, the login page for
    an anonymous visitor)."""
    from app.services.user_service import get_user

    user = await get_user(username)
    if user is not None and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return username
