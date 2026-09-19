"""settings_service.py had no dedicated tests at all (53% coverage, all of
it incidental from API integration tests). These focus on the encryption
path specifically: SENSITIVE_KEYS decides which settings get Fernet-
encrypted at rest, and webhook_url was missing from that set — Slack/
Discord/Telegram/ntfy webhook URLs carry their auth token directly in the
path, so storing one in plaintext is exactly the mistake SENSITIVE_KEYS
exists to prevent for smtp_password.
"""

from __future__ import annotations

import pytest

from app.services.settings_service import SENSITIVE_KEYS, SettingsService, settings_service


def test_webhook_url_is_treated_as_sensitive():
    """Regression test: webhook_url leaked into the DB in plaintext before
    this was added — any reader of a DB backup/dump could lift the Slack/
    Discord/etc auth token straight out of the URL path."""
    assert "webhook_url" in SENSITIVE_KEYS


class TestEncryptDecryptRoundTrip:
    def test_encrypt_then_decrypt_returns_the_original_value(self):
        svc = SettingsService()
        secret = "https://hooks.slack.com/services/T00/B00/super-secret-token"

        encrypted = svc._encrypt(secret)

        assert encrypted != secret
        assert svc._decrypt(encrypted) == secret

    def test_encrypted_value_is_not_readable_as_plaintext(self):
        svc = SettingsService()
        secret = "smtp-app-password-xyz"

        encrypted = svc._encrypt(secret)

        assert secret not in encrypted

    def test_empty_string_is_not_encrypted(self):
        """Nothing to protect, and an encrypted empty string is still a
        non-empty ciphertext — that would make "is a webhook configured?"
        checks (`if settings.webhook_url:`) see a non-empty value forever."""
        svc = SettingsService()
        assert svc._encrypt("") == ""

    def test_decrypting_unencrypted_legacy_value_returns_it_unchanged(self):
        """Values written before a key was added to SENSITIVE_KEYS (or
        before encryption existed at all) aren't Fernet tokens — decrypt
        must degrade gracefully instead of raising."""
        svc = SettingsService()
        assert svc._decrypt("plain-legacy-value") == "plain-legacy-value"

    def test_decrypting_with_a_different_secret_key_degrades_gracefully(self):
        """A value encrypted under one SECRET_KEY can't be decrypted under
        another (e.g. after a key rotation) — this must return the
        ciphertext as-is rather than raising and taking down the caller."""
        svc_a = SettingsService()
        svc_b = SettingsService()
        # Force distinct ciphers as if they had different SECRET_KEYs.
        from cryptography.fernet import Fernet

        svc_b._cipher = Fernet(Fernet.generate_key())

        encrypted_by_a = svc_a._encrypt("some-secret")
        result = svc_b._decrypt(encrypted_by_a)

        assert result == encrypted_by_a  # returned as-is, not raised


class TestSetAndGetRoundTripThroughTheDatabase:
    @pytest.mark.asyncio
    async def test_webhook_url_round_trips_decrypted_through_get(self, test_client):
        secret_url = "https://hooks.slack.com/services/T00/B00/round-trip-token"

        await settings_service.set("webhook_url", secret_url)
        result = await settings_service.get("webhook_url")

        assert result == secret_url

    @pytest.mark.asyncio
    async def test_webhook_url_is_encrypted_in_the_underlying_row(self, test_client, db_session):
        from sqlalchemy import select

        from app.models.setting import Setting

        secret_url = "https://hooks.slack.com/services/T00/B00/storage-check-token"
        await settings_service.set("webhook_url", secret_url)

        row = await db_session.execute(select(Setting).where(Setting.key == "webhook_url"))
        stored_value = row.scalar_one().value

        assert stored_value != secret_url
        assert secret_url not in stored_value

    @pytest.mark.asyncio
    async def test_non_sensitive_setting_is_stored_as_plaintext(self, test_client, db_session):
        from sqlalchemy import select

        from app.models.setting import Setting

        await settings_service.set("default_timeout", 1800)

        row = await db_session.execute(
            select(Setting).where(Setting.key == "default_timeout")
        )
        assert row.scalar_one().value == "1800"

    @pytest.mark.asyncio
    async def test_get_all_decrypts_sensitive_values(self, test_client):
        await settings_service.set("webhook_url", "https://example.com/hook-abc")
        await settings_service.set("default_timeout", 900)

        result = await settings_service.get_all()

        assert result["webhook_url"] == "https://example.com/hook-abc"
        assert result["default_timeout"] == 900
