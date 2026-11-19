"""The login session flow: /login, /logout.

The rest of the UI trusts nothing here to be logged in; these pages are
the *only* ones served without a session. After a successful login the
browser receives the session cookie and lands where it was heading;
logout clears it.

HTTP-only, SameSite=Lax: the session cookie is not readable from JS and
does not travel on cross-site requests. CSRF for the state-changing
POSTs is handled by the origin check the rest of the app already uses.
CSRF on the login POST itself is covered by the same origin guard.
"""

from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.api.dependencies import check_credentials
from app.api.rate_limit import record_login_failure
from app.services.auth_session import SESSION_TTL, create_session, delete_session

router = APIRouter()

SESSION_COOKIE_NAME = "cronator_session"
# Mirror auth_session's rule here so the cookie outlives nothing the
# server keeps.
SESSION_COOKIE_MAX_AGE = int(SESSION_TTL.total_seconds())


@router.get("/login")
async def login_form(request: Request, error: str | None = None) -> HTMLResponse:
    """The login page itself. No session required — that is its point."""
    resp = _render_login(request, error)
    return resp


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
) -> Response:
    """Validate credentials, hand back the session cookie."""
    from app.services.auth_session import purge_expired

    # Reuse the same gate the API's Basic Auth uses, so the lockout and
    # the env fallback behave identically on both paths.
    try:
        await check_credentials(username, password)
    except HTTPException:
        record_login_failure(username)
        return _render_login(request, error="Invalid username or password")

    token = await create_session(username)
    # Housekeeping: expired rows are dead weight once their owner logged
    # in again — but never let a failure here fail the login.
    try:
        await purge_expired()
    except Exception:  # pragma: no cover - defensive
        pass

    redirect_to = request.query_params.get("next") or "/"
    # open-redirect guard: only same-site paths, never a full URL
    if not redirect_to.startswith("/") or redirect_to.startswith("//"):
        redirect_to = "/"

    response = RedirectResponse(redirect_to, status_code=303)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=SESSION_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return response


@router.post("/logout")
async def logout(request: Request) -> RedirectResponse:
    """End the session server-side, then drop the cookie."""
    from app.main import logger

    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        await delete_session(token)
        logger.info("session: logged out via /logout")

    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response


def _render_login(request: Request, error: str | None = None) -> HTMLResponse:
    """The login page renders straight from a template, not the basic
    HTML-in-a-string from an early draft: the app already ships Jinja2,
    and escaping an injected error through a hand-built f-string is a
    foot-gun (a user-entered username echoed back in an error message
    would be an XSS)."""
    from fastapi.templating import Jinja2Templates

    templates = Jinja2Templates(directory="app/templates")
    return templates.TemplateResponse(
        request,
        name="login.html",
        context={"error": error},
    )
