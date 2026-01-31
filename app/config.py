"""Application configuration using pydantic-settings."""

import os
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    app_name: str = "Cronator"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8080

    # Database
    database_url: str = "sqlite+aiosqlite:///./data/cronator.db"

    # Database connection pooling (for PostgreSQL/MySQL)
    db_pool_size: int = 20
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    db_pool_recycle: int = 3600  # Recycle connections after 1 hour
    db_pool_pre_ping: bool = True  # Test connections before using

    # Directories
    base_dir: Path = Path(__file__).parent.parent
    scripts_dir: Path = Path("./scripts")
    envs_dir: Path = Path("./envs")
    logs_dir: Path = Path("./logs")
    data_dir: Path = Path("./data")
    artifacts_dir: Path = Path("./data/artifacts")

    @model_validator(mode="after")
    def make_paths_absolute(self) -> "Settings":
        """Convert relative paths to absolute based on base_dir."""
        if not self.scripts_dir.is_absolute():
            self.scripts_dir = self.base_dir / self.scripts_dir
        if not self.envs_dir.is_absolute():
            self.envs_dir = self.base_dir / self.envs_dir
        if not self.logs_dir.is_absolute():
            self.logs_dir = self.base_dir / self.logs_dir
        if not self.data_dir.is_absolute():
            self.data_dir = self.base_dir / self.data_dir
        if not self.artifacts_dir.is_absolute():
            self.artifacts_dir = self.base_dir / self.artifacts_dir

        import warnings

        suppress_config_warnings = bool(os.getenv("SUPPRESS_CONFIG_WARNINGS"))

        if not suppress_config_warnings:
            if not self.database_url or str(self.database_url).startswith("sqlite"):
                warnings.warn(
                    (
                        "DATABASE_URL is not set or points to SQLite; "
                        "use a production database in non-test environments."
                    ),
                    stacklevel=2,
                )

            if self.secret_key == "change-me-in-production-please" or len(self.secret_key) < 32:
                warnings.warn(
                    "SECRET_KEY is default or too short; set a strong random value (32+ chars).",
                    stacklevel=2,
                )

            if self.admin_password == "admin" or len(self.admin_password) < 8:
                warnings.warn(
                    "ADMIN_PASSWORD is default or weak; set a strong admin password.",
                    stacklevel=2,
                )

        return self

    # Authentication
    admin_username: str = "admin"
    admin_password: str = "admin"
    secret_key: str = "change-me-in-production-please"

    # SMTP for alerts
    smtp_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    alert_email: str = ""

    # Execution
    default_timeout: int = 3600  # 1 hour default timeout
    max_log_size: int = 1_000_000  # 1MB max stdout/stderr per execution

    # Artifacts
    max_artifact_size_mb: int = 10  # Maximum size per artifact file
    min_free_space_mb: int = 100  # Minimum free disk space required
    max_filename_length: int = 200  # Maximum filename length

    # UV settings
    uv_path: str = "uv"  # path to uv executable

    def ensure_directories(self) -> None:
        """Create required directories if they don't exist."""
        import logging
        import sys

        logger = logging.getLogger(__name__)

        for dir_path in [
            self.scripts_dir,
            self.envs_dir,
            self.logs_dir,
            self.data_dir,
            self.artifacts_dir,
        ]:
            try:
                dir_path.mkdir(parents=True, exist_ok=True)
            except (PermissionError, OSError) as e:
                # Log warning but don't fail - directories might be created externally
                # or have permission issues that don't prevent the app from running
                logger.warning(
                    f"Could not create directory {dir_path}: {e}. "
                    "The directory may already exist or have permission issues."
                )
                # Check if directory exists despite the error
                if not dir_path.exists():
                    # If it doesn't exist and we can't create it, this might be a problem
                    # but we'll continue anyway to allow the app to start
                    print(
                        f"Warning: Directory {dir_path} does not exist "
                        f"and could not be created: {e}",
                        file=sys.stderr,
                    )


_settings_cache: Settings | None = None


def get_settings(reload: bool = False) -> Settings:
    """Get settings instance with optional reload."""
    global _settings_cache
    if _settings_cache is None or reload:
        _settings_cache = Settings()
    return _settings_cache
