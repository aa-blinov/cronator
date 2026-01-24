"""Pydantic schemas for ScriptVersion model."""

from datetime import datetime

from pydantic import BaseModel, Field


class ScriptVersionBase(BaseModel):
    """Base schema for ScriptVersion."""

    version_number: int
    content: str
    dependencies: str = Field(default="")
    python_version: str = Field(default="3.11")
    cron_expression: str = Field(default="0 * * * *")
    timeout: int = Field(default=3600)
    environment_vars: str = Field(default="")
    change_summary: str | None = None


class ScriptVersionRead(ScriptVersionBase):
    """Schema for reading a script version."""

    id: int
    script_id: int
    created_at: datetime
    created_by: str

    model_config = {"from_attributes": True}


class ScriptVersionListItem(BaseModel):
    """Schema for listing script versions (without full content)."""

    id: int
    script_id: int
    version_number: int
    created_at: datetime
    created_by: str
    change_summary: str | None
    content_preview: str  # First 200 chars
    content_size: int  # Size in bytes

    model_config = {"from_attributes": True}


class ScriptVersionList(BaseModel):
    """Schema for listing script versions with pagination."""

    items: list[ScriptVersionListItem]
    total: int
