"""TDD tests for F14: HSTS (Strict-Transport-Security) header.

HSTS tells browsers to upgrade subsequent requests to HTTPS for max-age
seconds, mitigating protocol downgrade attacks. We only emit it when the
request arrived over HTTPS (or when ENABLE_HSTS=true in settings), so plain
HTTP localhost dev isn't permanently locked out of HTTPS-only.
"""

import pytest


@pytest.mark.asyncio
async def test_hsts_not_emitted_over_http_by_default(test_client):
    """Over plain HTTP (test_client default), HSTS is not emitted — dev safety."""
    r = await test_client.get("/")
    assert r.headers.get("strict-transport-security") is None


@pytest.mark.asyncio
async def test_hsts_emitted_when_request_is_https(test_client):
    """Over HTTPS (X-Forwarded-Proto=https), HSTS is emitted."""
    r = await test_client.get("/", headers={"X-Forwarded-Proto": "https"})
    hsts = r.headers.get("strict-transport-security")
    assert hsts is not None, "HSTS header missing over HTTPS"
    assert "max-age=" in hsts, hsts
    # 1 year minimum recommended
    max_age = int(hsts.split("max-age=")[1].split(";")[0].strip())
    assert max_age >= 31_536_000, f"max-age {max_age} too short (need >= 1 year)"


@pytest.mark.asyncio
async def test_hsts_includes_include_subdomains(test_client):
    """HSTS should include 'includeSubDomains' so the whole domain is HTTPS-only."""
    r = await test_client.get("/", headers={"X-Forwarded-Proto": "https"})
    hsts = r.headers.get("strict-transport-security", "")
    assert "includeSubDomains" in hsts, f"HSTS missing includeSubDomains: {hsts}"
