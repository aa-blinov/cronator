"""SECRET_KEY encrypts sensitive settings at rest (see settings_service._get_cipher).
The .env.example placeholder values are long enough to slip past the
length-only checks — 45 and 31 chars respectively — so a deploy that just
copies .env.example to .env without editing it would silently run with a
publicly-known encryption key. These pin down that it fails loudly instead.
"""

from __future__ import annotations

import pytest

from app.config import Settings

PLACEHOLDER_SECRET_KEY = "change-me-to-random-256-bit-key-in-production"
PLACEHOLDER_ADMIN_PASSWORD = "change-your-admin-password-here"


def test_rejects_placeholder_secret_key(monkeypatch):
    monkeypatch.setenv("SUPPRESS_CONFIG_WARNINGS", "1")
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(secret_key=PLACEHOLDER_SECRET_KEY, admin_password="a-real-password-123")


def test_rejects_placeholder_admin_password(monkeypatch):
    monkeypatch.setenv("SUPPRESS_CONFIG_WARNINGS", "1")
    with pytest.raises(ValueError, match="ADMIN_PASSWORD"):
        Settings(
            secret_key="a-real-randomly-generated-secret-key-value",
            admin_password=PLACEHOLDER_ADMIN_PASSWORD,
        )


def test_accepts_real_looking_values(monkeypatch):
    monkeypatch.setenv("SUPPRESS_CONFIG_WARNINGS", "1")
    settings = Settings(
        secret_key="a-real-randomly-generated-secret-key-value",
        admin_password="a-real-password-123",
    )
    assert settings.secret_key == "a-real-randomly-generated-secret-key-value"
