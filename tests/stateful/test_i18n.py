"""TDD tests for F15: Internationalization (i18n).

Add a /api/locales endpoint listing supported languages, a /api/locale
endpoint to get/set the active locale, and confirm Jinja templates render
translated strings via {% trans %} or the _() gettext-style helper.
"""

import pytest


@pytest.mark.asyncio
async def test_locales_endpoint(test_client):
    r = await test_client.get("/api/locales")
    assert r.status_code == 200
    body = r.json()
    assert "locales" in body
    locales = body["locales"]
    codes = {loc["code"] for loc in locales}
    assert "en" in codes, f"English missing: {codes}"
    assert "ru" in codes, f"Russian missing: {codes}"


@pytest.mark.asyncio
async def test_get_locale(test_client):
    r = await test_client.get("/api/locale")
    assert r.status_code == 200
    body = r.json()
    assert body.get("locale") in ("en", "ru"), body


@pytest.mark.asyncio
async def test_set_locale(test_client):
    r = await test_client.post("/api/locale", json={"locale": "ru"})
    assert r.status_code == 200, r.text
    # Verify persisted
    r = await test_client.get("/api/locale")
    assert r.json()["locale"] == "ru", r.json()
    # Reset
    await test_client.post("/api/locale", json={"locale": "en"})


@pytest.mark.asyncio
async def test_set_locale_rejects_unknown(test_client):
    r = await test_client.post("/api/locale", json={"locale": "xx"})
    assert r.status_code == 422 or r.status_code == 400
