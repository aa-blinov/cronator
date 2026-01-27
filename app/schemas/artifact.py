"""Pydantic schemas for artifacts."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ArtifactBase(BaseModel):
    """Base artifact schema."""

    execution_id: int
    filename: str
    original_filename: str
    size_bytes: int


class ArtifactRead(ArtifactBase):
    """Schema for reading an artifact."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class ArtifactList(BaseModel):
    """Schema for listing artifacts."""

    items: list[ArtifactRead]
    total: int
