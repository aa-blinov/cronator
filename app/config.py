"""Application configuration using pydantic-settings."""

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

        # Validate production secrets ONLY in non-debug mode
        # In development (DEBUG=True), default values are acceptable
        if not self.debug:
            if self.secret_key == "change-me-in-production-please":
                import warnings

                warnings.warn(
                    "SECRET_KEY is using default value in production! "
                    "Set a secure random value in environment or .env file.",
                    stacklevel=2,
                )
            if self.admin_password == "admin":
                import warnings

                warnings.warn(
                    "ADMIN_PASSWORD is using default value in production! "
                    "Set a secure password in environment or .env file.",
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
    smtp_use_tls: bool = True
    alert_email: str = ""

    # Git sync
    git_enabled: bool = False
    git_repo_url: str = ""
    git_branch: str = "main"
    git_token: str = ""  # Personal access token for private repos
    git_sync_interval: int = 300  # seconds
    git_scripts_subdir: str = ""  # subdirectory in repo for scripts

    # Execution
    default_timeout: int = 3600  # 1 hour default timeout
    max_log_size: int = 1_000_000  # 1MB max stdout/stderr per execution

    # UV settings
    uv_path: str = "uv"  # path to uv executable

    def ensure_directories(self) -> None:
        """Create required directories if they don't exist."""
        for dir_path in [self.scripts_dir, self.envs_dir, self.logs_dir, self.data_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)


_settings_cache: Settings | None = None


def get_settings(reload: bool = False) -> Settings:
    """Get settings instance with optional reload."""
    global _settings_cache
    if _settings_cache is None or reload:
        _settings_cache = Settings()
    return _settings_cache
