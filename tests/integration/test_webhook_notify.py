"""TDD tests for F17: webhook notifications.

Operators can configure a webhook URL (Slack/Discord/PagerDuty/etc.) to
receive Cronator failure alerts. The notification is sent as a JSON POST.
"""

import pytest


@pytest.mark.asyncio
async def test_settings_accepts_webhook_url(test_client):
    """Settings API must accept a webhook_url field."""
    r = await test_client.post(
        "/api/settings/update",
        json={"webhook_url": "https://hooks.slack.com/services/T/B/X"},
    )
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_settings_exposes_webhook_url(test_client):
    """GET /api/settings must expose webhook_url after it's been set."""
    # Set the value first (the test_client fixture is per-test, so each test
    # starts with a fresh DB).
    r = await test_client.post(
        "/api/settings/update",
        json={"webhook_url": "https://hooks.example.com/test"},
    )
    assert r.status_code == 200, r.text
    # Now GET should reflect it
    r = await test_client.get("/api/settings")
    assert r.status_code == 200
    body = r.json()
    assert "webhook_url" in body
    assert body["webhook_url"] == "https://hooks.example.com/test"


@pytest.mark.asyncio
async def test_test_webhook_endpoint(test_client):
    """POST /api/settings/test-webhook sends a sample payload to the configured URL."""
    r = await test_client.post(
        "/api/settings/test-webhook",
        json={"webhook_url": "https://httpbin.org/post"},
    )
    # Either success (200) or a 502 if network is unavailable in CI — both are
    # acceptable for the existence test.
    assert r.status_code in (200, 502, 503), r.text
