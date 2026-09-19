"""DB round-trip half of settings_service encryption coverage — see
tests/stateless/services/test_settings_service_encryption.py for the pure
encrypt/decrypt logic (no DB fixtures there).
"""

from __future__ import annotations

import pytest

from app.services.settings_service import settings_service


@pytest.mark.asyncio
async def test_webhook_url_round_trips_decrypted_through_get(test_client):
    secret_url = "https://hooks.slack.com/services/T00/B00/round-trip-token"

    await settings_service.set("webhook_url", secret_url)
    result = await settings_service.get("webhook_url")

    assert result == secret_url


@pytest.mark.asyncio
async def test_webhook_url_is_encrypted_in_the_underlying_row(test_client, db_session):
    from sqlalchemy import select

    from app.models.setting import Setting

    secret_url = "https://hooks.slack.com/services/T00/B00/storage-check-token"
    await settings_service.set("webhook_url", secret_url)

    row = await db_session.execute(select(Setting).where(Setting.key == "webhook_url"))
    stored_value = row.scalar_one().value

    assert stored_value != secret_url
    assert secret_url not in stored_value


@pytest.mark.asyncio
async def test_non_sensitive_setting_is_stored_as_plaintext(test_client, db_session):
    from sqlalchemy import select

    from app.models.setting import Setting

    await settings_service.set("default_timeout", 1800)

    row = await db_session.execute(select(Setting).where(Setting.key == "default_timeout"))
    assert row.scalar_one().value == "1800"


@pytest.mark.asyncio
async def test_get_all_decrypts_sensitive_values(test_client):
    await settings_service.set("webhook_url", "https://example.com/hook-abc")
    await settings_service.set("default_timeout", 900)

    result = await settings_service.get_all()

    assert result["webhook_url"] == "https://example.com/hook-abc"
    assert result["default_timeout"] == 900
