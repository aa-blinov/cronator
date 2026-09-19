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

    # Artifacts tracking
    artifacts_count: int = 0
    artifacts_size_bytes: int = 0

    # Computed fields
    duration_formatted: str = "-"
    script_name: str | None = None

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "example": {
                "id": 42,
                "script_id": 1,
                "status": "success",
                "started_at": "2026-09-16T18:33:46.060663Z",
                "finished_at": "2026-09-16T18:33:49.197953Z",
                "duration_ms": 3137,
                "exit_code": 0,
                "stdout": '{"timestamp": "...", "level": "INFO", "message": "done"}\n',
                "stderr": "",
                "triggered_by": "manual",
                "is_test": False,
                "error_message": None,
                "artifacts_count": 0,
                "artifacts_size_bytes": 0,
                "duration_formatted": "3.1s",
                "script_name": "daily-report",
            }
        },
    }


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
