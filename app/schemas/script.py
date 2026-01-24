"""Pydantic schemas for Script model."""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class ScriptBase(BaseModel):
    """Base schema for Script."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="")
    cron_expression: str = Field(default="0 * * * *")
    enabled: bool = Field(default=True)
    python_version: str = Field(default="3.11")
    dependencies: str = Field(default="")
    alert_on_failure: bool = Field(default=True)
    alert_on_success: bool = Field(default=False)
    timeout: int = Field(default=3600, ge=1, le=86400)
    misfire_grace_time: int = Field(default=60, ge=0, le=3600)
    working_directory: str = Field(default="")
    environment_vars: str = Field(default="")

    @field_validator("cron_expression")
    @classmethod
    def validate_cron(cls, v: str) -> str:
        """Basic cron expression validation."""
        parts = v.strip().split()
        if len(parts) != 5:
            raise ValueError("Cron expression must have 5 parts (minute hour day month weekday)")
        return v.strip()

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate script name."""
        v = v.strip()
        if not v:
            raise ValueError("Name cannot be empty")

        # Length checks
        if len(v) < 2:
            raise ValueError("Name must be at least 2 characters")
        if len(v) > 100:  # Reasonable limit for directory name
            raise ValueError("Name must be 100 characters or less")

        # Only allow safe characters for filesystem
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
        if not all(c in allowed for c in v):
            raise ValueError("Name can only contain letters, numbers, underscores, and hyphens")

        # Cannot start or end with hyphen/underscore (convention)
        if v[0] in "-_" or v[-1] in "-_":
            raise ValueError("Name cannot start or end with hyphen or underscore")

        # Check for reserved names (Windows)
        reserved_windows = {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            "COM1",
            "COM2",
            "COM3",
            "COM4",
            "COM5",
            "COM6",
            "COM7",
            "COM8",
            "COM9",
            "LPT1",
            "LPT2",
            "LPT3",
            "LPT4",
            "LPT5",
            "LPT6",
            "LPT7",
            "LPT8",
            "LPT9",
        }
        if v.upper() in reserved_windows:
            raise ValueError(f"'{v}' is a reserved name on Windows systems")

        # Check for Unix-reserved names
        if v in (".", ".."):
            raise ValueError("Cannot use '.' or '..' as name")

        return v


class ScriptCreate(ScriptBase):
    """Schema for creating a new script."""

    content: str = Field(default="")  # Script content for UI-created scripts
    path: str = Field(default="")  # Optional path for file-based scripts


class ScriptUpdate(BaseModel):
    """Schema for updating a script (all fields optional)."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    content: str | None = None
    cron_expression: str | None = None
    enabled: bool | None = None
    python_version: str | None = None
    dependencies: str | None = None
    alert_on_failure: bool | None = None
    alert_on_success: bool | None = None
    timeout: int | None = Field(default=None, ge=1, le=86400)
    misfire_grace_time: int | None = Field(default=None, ge=0, le=3600)
    working_directory: str | None = None
    environment_vars: str | None = None
    change_summary: str | None = None  # Optional description of changes for versioning

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        """Validate script name."""
        if v is None:
            return v
        # Use same validation as ScriptCreate
        return ScriptBase.validate_name(v)

    @field_validator("cron_expression")
    @classmethod
    def validate_cron(cls, v: str | None) -> str | None:
        """Basic cron expression validation."""
        if v is None:
            return v
        parts = v.strip().split()
        if len(parts) != 5:
            raise ValueError("Cron expression must have 5 parts")
        return v.strip()


class ScriptRead(ScriptBase):
    """Schema for reading a script."""

    id: int
    path: str
    content: str
    created_at: datetime
    updated_at: datetime
    git_commit: str | None = None

    # Computed fields for UI
    last_run_status: str | None = None
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    last_alert_at: datetime | None = None
    is_managed_by_git: bool = False

    model_config = {"from_attributes": True}


class ScriptReadWithInstallStatus(ScriptRead):
    """Schema for reading a script with installation status flag."""

    needs_install: bool = Field(
        default=False,
        description="Whether dependencies or Python version changed and installation is needed",
    )


class ScriptList(BaseModel):
    """Schema for listing scripts with pagination."""

    items: list[ScriptRead]
    total: int
    page: int
    per_page: int
    pages: int
