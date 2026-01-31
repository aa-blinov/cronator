"""Service for managing runtime settings stored in database."""

import json
import logging
from typing import Any

from cryptography.fernet import Fernet
from sqlalchemy import select

from app.config import get_settings
from app.database import async_session_maker
from app.models.setting import Setting

logger = logging.getLogger(__name__)

# List of sensitive keys that should be encrypted
SENSITIVE_KEYS = {
    "smtp_password",
    "admin_password",  # If we ever store it in DB
}


class SettingsService:
    """Service for managing runtime settings."""

    def __init__(self) -> None:
        self._cache: dict[str, str] = {}
        self._loaded = False
        self._cipher = self._get_cipher()

    def _get_cipher(self) -> Fernet:
        """Get encryption cipher using secret key from config."""
        import hashlib
        from base64 import urlsafe_b64encode

        env_settings = get_settings()
        # Use secret_key as basis for encryption key
        # Ensure it's 32 bytes URL-safe base64-encoded

        # Derive a proper Fernet key from secret_key
        key_material = hashlib.sha256(env_settings.secret_key.encode()).digest()
        fernet_key = urlsafe_b64encode(key_material)

        return Fernet(fernet_key)

    async def load_from_db(self) -> None:
        """Load all settings from database into cache."""
        async with async_session_maker() as db:
            result = await db.execute(select(Setting))
            settings = result.scalars().all()

            self._cache = {s.key: s.value for s in settings}
            self._loaded = True

        logger.info(f"Loaded {len(self._cache)} settings from database")

    async def get(self, key: str, default: Any = None) -> Any:
        """Get a setting value from database, fallback to env var."""
        if not self._loaded:
            await self.load_from_db()

        # Check database cache first
        if key in self._cache:
            value = self._cache[key]
            # Decrypt if sensitive
            if key in SENSITIVE_KEYS:
                value = self._decrypt(value)
            return self._parse_value(value)

        # Fallback to env settings
        env_settings = get_settings()
        if hasattr(env_settings, key):
            return getattr(env_settings, key)

        return default

    async def set(self, key: str, value: Any) -> None:
        """Set a setting value in database."""
        str_value = self._serialize_value(value)

        # Encrypt if sensitive
        if key in SENSITIVE_KEYS and str_value:
            str_value = self._encrypt(str_value)

        async with async_session_maker() as db:
            result = await db.execute(select(Setting).where(Setting.key == key))
            setting = result.scalar_one_or_none()

            if setting:
                setting.value = str_value
            else:
                setting = Setting(key=key, value=str_value)
                db.add(setting)

            await db.commit()

        # Update cache
        self._cache[key] = str_value
        logger.info(f"Updated setting: {key}={'***' if key in SENSITIVE_KEYS else value}")

    async def get_all(self) -> dict[str, Any]:
        """Get all settings as a dictionary."""
        if not self._loaded:
            await self.load_from_db()

        result = {}
        for key, value in self._cache.items():
            # Decrypt if sensitive
            if key in SENSITIVE_KEYS:
                value = self._decrypt(value)
            result[key] = self._parse_value(value)

        return result

    async def bulk_set(self, settings: dict[str, Any]) -> None:
        """Set multiple settings at once."""
        async with async_session_maker() as db:
            for key, value in settings.items():
                str_value = self._serialize_value(value)

                # Encrypt if sensitive
                if key in SENSITIVE_KEYS and str_value:
                    str_value = self._encrypt(str_value)

                result = await db.execute(select(Setting).where(Setting.key == key))
                setting = result.scalar_one_or_none()

                if setting:
                    setting.value = str_value
                else:
                    setting = Setting(key=key, value=str_value)
                    db.add(setting)

                # Update cache
                self._cache[key] = str_value

            await db.commit()

        logger.info(f"Updated {len(settings)} settings")

    async def delete(self, key: str) -> bool:
        """Delete a setting from database."""
        async with async_session_maker() as db:
            result = await db.execute(select(Setting).where(Setting.key == key))
            setting = result.scalar_one_or_none()

            if setting:
                await db.delete(setting)
                await db.commit()
                self._cache.pop(key, None)
                logger.info(f"Deleted setting: {key}")
                return True

        return False

    def _serialize_value(self, value: Any) -> str:
        """Convert value to string for storage."""
        if isinstance(value, bool):
            return "true" if value else "false"
        elif isinstance(value, int | float):
            return str(value)
        elif isinstance(value, str):
            return value
        else:
            # For complex types, use JSON
            return json.dumps(value)

    def _parse_value(self, value: str) -> Any:
        """Parse string value from database."""
        # Try boolean
        if value.lower() in ("true", "false"):
            return value.lower() == "true"

        # Try int
        try:
            return int(value)
        except ValueError:
            pass

        # Try float
        try:
            return float(value)
        except ValueError:
            pass

        # Try JSON
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            pass

        # Return as string
        return value

    def _encrypt(self, value: str) -> str:
        """Encrypt a sensitive value."""
        if not value:
            return value
        try:
            encrypted = self._cipher.encrypt(value.encode())
            return encrypted.decode()
        except Exception as e:
            logger.error(f"Failed to encrypt value: {e}")
            return value

    def _decrypt(self, value: str) -> str:
        """Decrypt a sensitive value."""
        if not value:
            return value
        try:
            decrypted = self._cipher.decrypt(value.encode())
            return decrypted.decode()
        except Exception as e:
            # Value might not be encrypted (legacy data)
            logger.warning(f"Failed to decrypt value, returning as-is: {e}")
            return value

    async def migrate_from_env(self) -> int:
        """Migrate settings from .env to database (one-time migration)."""
        env_settings = get_settings()

        settings_to_migrate = {
            "smtp_enabled": env_settings.smtp_enabled,
            "smtp_host": env_settings.smtp_host,
            "smtp_port": env_settings.smtp_port,
            "smtp_user": env_settings.smtp_user,
            "smtp_password": env_settings.smtp_password,
            "smtp_from": env_settings.smtp_from,
            "alert_email": env_settings.alert_email,
            "default_timeout": env_settings.default_timeout,
        }

        # Only migrate non-empty/non-default values
        to_save = {}
        for key, value in settings_to_migrate.items():
            # Skip empty strings and default boolean false
            if value == "" or value == 0:
                continue
            if isinstance(value, bool) and not value:
                continue

            # Check if already exists in DB
            if key not in self._cache:
                to_save[key] = value

        if to_save:
            await self.bulk_set(to_save)
            logger.info(f"Migrated {len(to_save)} settings from .env to database")

        return len(to_save)


# Global instance
settings_service = SettingsService()
