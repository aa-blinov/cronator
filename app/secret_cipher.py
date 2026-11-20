"""Fernet helpers for values that must not sit in the database in plaintext.

`settings_service` encrypts its SENSITIVE_KEYS on its own read/write paths;
scripts and script versions needed the same treatment for
`environment_vars`, which is exactly where operators put database passwords
and API tokens. The key derivation is identical to the settings one (sha256
of SECRET_KEY), so it lives here once instead of drifting between two
copies.
"""

import hashlib
import logging
from base64 import urlsafe_b64encode
from functools import lru_cache

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

# Marker that tells an encrypted value apart from legacy plaintext without
# guessing. settings_service stores bare tokens (its decrypt falls back to
# returning the input on failure); every other encrypted column uses this
# prefix so `is_encrypted` stays a cheap string check.
ENCRYPTED_PREFIX = "enc:v1:"


@lru_cache(maxsize=1)
def get_cipher() -> Fernet:
    """Derive the Fernet key from SECRET_KEY, same as the settings table."""
    # Imported lazily: app.config reads the environment at call time, and
    # importing it at module level would run that on every import of a model.
    from app.config import get_settings

    key_material = hashlib.sha256(get_settings().secret_key.encode()).digest()
    return Fernet(urlsafe_b64encode(key_material))


def is_encrypted(value: str | None) -> bool:
    """True when the value carries the encrypted-storage marker."""
    return bool(value) and value.startswith(ENCRYPTED_PREFIX)


def encrypt_secret(value: str) -> str:
    """Encrypt a value for storage.

    Empty and already-encrypted values pass through unchanged. A cipher
    failure logs and also passes through — fail-open, the same contract the
    settings service established: refusing a save because the column could
    not be encrypted leaves the operator worse off than the plaintext they
    already had.
    """
    if not value or is_encrypted(value):
        return value
    try:
        token = get_cipher().encrypt(value.encode()).decode()
        return ENCRYPTED_PREFIX + token
    except Exception as e:
        logger.error("Failed to encrypt a stored value: %s", e)
        return value


def decrypt_secret(value: str) -> str:
    """Decrypt a stored value.

    Legacy plaintext (no marker) passes through unchanged, so rows written
    before the encrypted column type existed keep working until the startup
    sweep rewrites them.
    """
    if not value or not is_encrypted(value):
        return value
    try:
        token = value[len(ENCRYPTED_PREFIX) :].encode()
        return get_cipher().decrypt(token).decode()
    except Exception as e:
        # A rotated SECRET_KEY makes old values unreadable — surface the raw
        # stored string rather than take down every read path with it.
        logger.warning("Failed to decrypt a stored value, returning as-is: %s", e)
        return value
