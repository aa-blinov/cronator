"""Security headers middleware for F1 + F14.

Adds the minimum headers required by the OWASP Secure Headers baseline to
every HTTP response. Headers are deliberately conservative:

- X-Content-Type-Options: nosniff             (prevent MIME sniffing)
- X-Frame-Options: DENY                       (prevent clickjacking)
- Referrer-Policy: strict-origin-when-cross-origin  (limit referrer leak)
- Permissions-Policy: camera/mic/geo=()      (block unused sensitive APIs)
- Content-Security-Policy: restrictive defaults (allow self only)
- Strict-Transport-Security (F14, HTTPS only)  (force HTTPS for 1 year)

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
# - data: for images allows inline favicons; https: for fonts allows Google Fonts loaded in base.html.  # noqa: E501
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

# 1 year is the recommended minimum for HSTS qualification in browsers' preload list.
HSTS_VALUE = "max-age=31536000; includeSubDomains"


def _is_https(request: Request) -> bool:
    """Detect HTTPS — either direct scheme or via X-Forwarded-Proto (reverse proxy)."""
    if request.url.scheme == "https":
        return True
    forwarded_proto = request.headers.get("x-forwarded-proto", "").lower()
    return forwarded_proto == "https"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", REFERRER_POLICY)
        response.headers.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
        response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)

        # Only emit HSTS over HTTPS — emitting it over plain HTTP would lock
        # the browser into HTTPS for max-age seconds on a host that's only HTTP.
        if _is_https(request):
            response.headers.setdefault("Strict-Transport-Security", HSTS_VALUE)

        return response
