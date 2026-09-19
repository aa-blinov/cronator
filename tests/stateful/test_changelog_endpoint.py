"""TDD tests for F4: CHANGELOG.md endpoint."""

import pytest


@pytest.mark.asyncio
async def test_changelog_endpoint_returns_200(test_client):
    r = await test_client.get("/changelog")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_changelog_endpoint_renders_content(test_client):
    r = await test_client.get("/changelog")
    assert r.status_code == 200
    body = r.text
    # At minimum we expect the page to render markdown headings as HTML
    assert "<h1" in body or "<h2" in body, body[:500]
    # And include a Back link
    assert "Back" in body or "back" in body


@pytest.mark.asyncio
async def test_changelog_has_security_headers(test_client):
    """Changelog page must also carry F1 security headers."""
    r = await test_client.get("/changelog")
    assert r.status_code == 200
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"
