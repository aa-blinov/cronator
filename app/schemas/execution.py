"""Pydantic schemas for Execution model."""

from datetime import datetime

from pydantic import BaseModel, Field


class ExecutionBase(BaseModel):
    """Base schema for Execution."""

    script_id: int
    triggered_by: str = Field(default="scheduler")
    is_test: bool = Field(default=False)


class ExecutionCreate(ExecutionBase):
    """Schema for creating a new execution."""

    pass


class ExecutionRead(BaseModel):
    """Schema for reading an execution."""

    id: int
    script_id: int
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    triggered_by: str = "scheduler"
    is_test: bool = False
    error_message: str | None = None
    
    # Computed fields
    duration_formatted: str = "-"
    script_name: str | None = None

    model_config = {"from_attributes": True}


class ExecutionList(BaseModel):
    """Schema for listing executions with pagination."""

    items: list[ExecutionRead]
    total: int
    page: int
    per_page: int
    pages: int


class ExecutionStats(BaseModel):
    """Statistics about executions."""

    total_executions: int = 0
    successful: int = 0
    failed: int = 0
    running: int = 0
    success_rate: float = 0.0
    avg_duration_ms: float | None = None
