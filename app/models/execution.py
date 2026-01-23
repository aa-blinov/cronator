"""Execution model for storing script run history."""

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.script import Script


class ExecutionStatus(str, Enum):
    """Status of a script execution."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class Execution(Base):
    """Model representing a single script execution."""

    __tablename__ = "executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    script_id: Mapped[int] = mapped_column(
        Integer, 
        ForeignKey("scripts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    # Execution status
    status: Mapped[str] = mapped_column(
        String(20), 
        default=ExecutionStatus.PENDING.value,
        index=True,
    )
    
    # Timing
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    
    # Results
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stdout: Mapped[str] = mapped_column(Text, default="")
    stderr: Mapped[str] = mapped_column(Text, default="")
    
    # Trigger info
    # scheduler, manual, api
    triggered_by: Mapped[str] = mapped_column(
        String(50), default="scheduler"
    )
    
    # Test execution flag
    is_test: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    
    # Error details
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # Relationships
    script: Mapped["Script"] = relationship("Script", back_populates="executions")

    def __repr__(self) -> str:
        return f"<Execution(id={self.id}, script_id={self.script_id}, status='{self.status}')>"

    @property
    def is_finished(self) -> bool:
        """Check if execution has finished."""
        return self.status in (
            ExecutionStatus.SUCCESS.value,
            ExecutionStatus.FAILED.value,
            ExecutionStatus.TIMEOUT.value,
            ExecutionStatus.CANCELLED.value,
        )

    @property
    def duration_formatted(self) -> str:
        """Get human-readable duration."""
        if self.duration_ms is None:
            return "-"
        
        seconds = self.duration_ms / 1000
        if seconds < 60:
            return f"{seconds:.1f}s"
        elif seconds < 3600:
            return f"{seconds / 60:.1f}m"
        else:
            return f"{seconds / 3600:.1f}h"
