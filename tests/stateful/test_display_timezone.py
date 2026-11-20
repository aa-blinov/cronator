"""The display-timezone setting, end to end: API accepts it, the pages
render stored UTC timestamps in the operator's zone and name the zone.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.services.settings_service import settings_service


@pytest.fixture(autouse=True)
def _reset_display_timezone_cache():
    """The settings singleton is shared across the test process; a zone set
    here must not leak into other pages' rendering."""
    settings_service._cache.pop("display_timezone", None)
    yield
    settings_service._cache.pop("display_timezone", None)


async def test_update_accepts_valid_timezone(test_client):
    r = await test_client.post("/api/settings/update", json={"display_timezone": "Europe/Moscow"})
    assert r.status_code == 200, r.text

    info = await test_client.get("/api/settings")
    assert info.json()["display_timezone"] == "Europe/Moscow"


async def test_update_rejects_unknown_timezone(test_client):
    r = await test_client.post("/api/settings/update", json={"display_timezone": "Not/AZone"})
    assert r.status_code == 422, r.text


async def test_empty_timezone_means_utc(test_client):
    r = await test_client.post("/api/settings/update", json={"display_timezone": ""})
    assert r.status_code == 200, r.text
    assert (await test_client.get("/api/settings")).json()["display_timezone"] == "UTC"


async def test_dashboard_renders_in_display_timezone(
    test_client, script_factory, execution_factory
):
    await test_client.post("/api/settings/update", json={"display_timezone": "Europe/Moscow"})

    script = await script_factory(name="tz_render_script", content="print(1)", enabled=True)
    await execution_factory(
        script_id=script.id,
        status="success",
        started_at=datetime(2026, 11, 20, 12, 0, 0, tzinfo=UTC),
    )

    r = await test_client.get("/")
    assert r.status_code == 200

    # 12:00 UTC is 15:00 MSK, and the rendering names its zone.
    assert "2026-11-20 15:00 MSK" in r.text, "expected Moscow rendering in the dashboard"


async def test_dashboard_defaults_to_utc_with_a_marker(
    test_client, script_factory, execution_factory
):
    script = await script_factory(name="tz_default_script", content="print(1)", enabled=True)
    await execution_factory(
        script_id=script.id,
        status="success",
        started_at=datetime(2026, 11, 20, 12, 0, 0, tzinfo=UTC),
    )

    r = await test_client.get("/")
    assert r.status_code == 200
    # Even the default now says which zone the reader is looking at.
    assert "2026-11-20 12:00 UTC" in r.text
