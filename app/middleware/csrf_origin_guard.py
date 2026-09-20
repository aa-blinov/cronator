"""CSRF mitigation for Basic Auth (P0).

Browsers auto-attach cached Basic Auth credentials to every request to an
origin they were entered for, regardless of which page initiated the
request — so a form on an attacker's site can submit a state-changing
request here and have it silently authenticated. There's no session
cookie to mark SameSite, so the usual CSRF-cookie defenses don't apply.

Mitigation: on state-changing methods, if the request carries an `Origin`
header, it must match this app's own origin. Browsers always send Origin
on cross-origin requests (including plain HTML form submissions, not
just fetch/XHR); they don't for non-browser clients (curl, server-to-server
API calls), so those are left alone — this targets the browser-credential-
replay vector specifically, not API automation.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

STATE_CHANGING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class CsrfOriginGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if request.method in STATE_CHANGING_METHODS:
            origin = request.headers.get("origin")
            if origin is not None:
                # Trust X-Forwarded-Proto same as SecurityHeadersMiddleware
                # does — behind a TLS-terminating reverse proxy (the
                # documented deployment) request.url.scheme is "http" even
                # though the browser's real, public-facing origin is https.
                forwarded_proto = request.headers.get("x-forwarded-proto", "").lower()
                scheme = "https" if forwarded_proto == "https" else request.url.scheme
                expected = f"{scheme}://{request.url.netloc}"
                if origin != expected:
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "Cross-origin request blocked"},
                    )
        return await call_next(request)
