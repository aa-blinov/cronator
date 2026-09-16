"""Security headers middleware for F1.

Adds the minimum headers required by the OWASP Secure Headers baseline to
every HTTP response. Headers are deliberately conservative:

- X-Content-Type-Options: nosniff             (prevent MIME sniffing)
- X-Frame-Options: DENY                       (prevent clickjacking)
- Referrer-Policy: strict-origin-when-cross-origin  (limit referrer leak)
- Permissions-Policy: camera/mic/geo=()      (block unused sensitive APIs)
- Content-Security-Policy: restrictive defaults (allow self only)

The middleware is registered globally in app/main.py after the FastAPI app
is created and before routers are included, so it covers error responses too.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Restrictive CSP that still lets the Tailwind CSS, fonts, and inline UI scripts work.
# - 'self' is the same-origin source for scripts, styles, images, etc.
# - 'unsafe-inline' for style is required by Tailwind utility classes generated dynamically.
# - data: for images allows inline favicons; https: for fonts allows Google Fonts loaded in base.html.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "img-src 'self' data: https:; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self' 'unsafe-inline'; "
    "font-src 'self' https: data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)

PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"

REFERRER_POLICY = "strict-origin-when-cross-origin"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", REFERRER_POLICY)
        response.headers.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
        response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        return response
