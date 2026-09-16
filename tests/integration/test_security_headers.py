"""TDD tests for F1: Security Headers Middleware.

Headers required on every HTTP response:
- X-Content-Type-Options: nosniff
- X-Frame-Options: DENY
- Referrer-Policy: strict-origin-when-cross-origin
- Permissions-Policy: camera=(), microphone=(), geolocation=()
- Content-Security-Policy (default-src 'self')

These are the minimum that a self-hosted app must emit by default — without
them the app fails the OWASP Secure Headers Project baseline.
"""

import pytest
from httpx import AsyncClient

REQUIRED_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin-when-cross-origin",
}


@pytest.mark.asyncio
async def test_root_response_has_security_headers(test_client):
    """GET / must emit every required security header."""
    response = await test_client.get("/")
    assert response.status_code == 200
    for header, expected in REQUIRED_HEADERS.items():
        assert header in response.headers, f"missing header {header}"
        assert response.headers[header] == expected, (
            f"header {header} has value {response.headers[header]!r}, expected {expected!r}"
        )


@pytest.mark.asyncio
async def test_api_response_has_security_headers(test_client):
    """GET /api/scripts must also emit security headers (headers middleware is global)."""
    response = await test_client.get("/api/scripts")
    assert response.status_code == 200
    for header, expected in REQUIRED_HEADERS.items():
        assert response.headers.get(header) == expected


@pytest.mark.asyncio
async def test_404_response_has_security_headers(test_client):
    """Security headers must be present even on error responses."""
    response = await test_client.get("/api/scripts/99999")
    assert response.status_code == 404
    for header, expected in REQUIRED_HEADERS.items():
        assert response.headers.get(header) == expected


@pytest.mark.asyncio
async def test_csp_header_present(test_client):
    """A Content-Security-Policy header must be set."""
    response = await test_client.get("/")
    csp = response.headers.get("content-security-policy", "")
    assert csp, "Content-Security-Policy header missing"
    assert "default-src 'self'" in csp, f"CSP must restrict default-src to self, got: {csp}"


@pytest.mark.asyncio
async def test_permissions_policy_restricts_sensitive_apis(test_client):
    """Permissions-Policy must disable camera, microphone, geolocation by default."""
    response = await test_client.get("/")
    pp = response.headers.get("permissions-policy", "")
    assert pp, "Permissions-Policy header missing"
    for feature in ("camera", "microphone", "geolocation"):
        assert f"{feature}=()" in pp, f"Permissions-Policy must block {feature}, got: {pp}"
