"""Pure encrypt/decrypt logic — no DB involved. See
tests/stateful/test_settings_service_db.py for the DB round-trip half
of this coverage (split out so this file has no stateful fixtures).
"""

from __future__ import annotations

from app.services.settings_service import SENSITIVE_KEYS, SettingsService


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
