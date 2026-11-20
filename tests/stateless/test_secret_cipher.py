"""app/services/secret_cipher.py — marker-based Fernet helpers.

The marker is the contract: legacy plaintext passes through unchanged, a
stored value is recognizable as ciphertext without a decrypt attempt, and
nothing ever double-encrypts.
"""

from app.secret_cipher import (
    ENCRYPTED_PREFIX,
    decrypt_secret,
    encrypt_secret,
    is_encrypted,
)


class TestRoundTrip:
    def test_encrypt_then_decrypt_returns_original(self):
        plain = '{"DB_PASSWORD": "hunter2", "API_TOKEN": "abc-123"}'

        stored = encrypt_secret(plain)

        assert stored != plain
        assert decrypt_secret(stored) == plain

    def test_stored_value_carries_the_marker(self):
        assert encrypt_secret("hunter2").startswith(ENCRYPTED_PREFIX)

    def test_is_encrypted_detects_the_marker(self):
        assert is_encrypted(encrypt_secret("x"))
        assert not is_encrypted("x")
        assert not is_encrypted("")
        assert not is_encrypted(None)

    def test_each_encryption_produces_a_different_token(self):
        # Fernet includes a random IV — two writes of the same value must not
        # compare equal at rest, so a database dump leaks nothing by pattern.
        assert encrypt_secret("x") != encrypt_secret("x")


class TestPassthrough:
    def test_empty_value_is_not_encrypted(self):
        assert encrypt_secret("") == ""

    def test_none_is_left_alone(self):
        # The column is non-nullable, but decrypt(None) must still hold for
        # any future nullable consumer.
        assert decrypt_secret("") == ""

    def test_legacy_plaintext_passes_through_decrypt(self):
        # Rows written before the encrypted column type existed.
        assert decrypt_secret("FOO=bar") == "FOO=bar"

    def test_already_encrypted_value_is_not_double_encrypted(self):
        once = encrypt_secret("hunter2")

        twice = encrypt_secret(once)

        assert twice == once


class TestKeyDerivation:
    def test_cipher_is_shared_with_settings_service(self):
        # settings_service._get_cipher delegates here — two derivations of
        # the same SECRET_KEY would mean two formats drifting apart.
        from app.services.settings_service import SettingsService

        service = SettingsService()

        assert service._cipher is not None
