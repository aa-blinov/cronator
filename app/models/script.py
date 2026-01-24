"""Script model for storing script configurations."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.execution import Execution


class Script(Base):
    """Model representing a scheduled Python script."""

    __tablename__ = "scripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")

    # Script content and path
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")  # For UI-created scripts

    # Scheduling
    cron_expression: Mapped[str] = mapped_column(String(100), default="0 * * * *")  # Every hour
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # Environment
    python_version: Mapped[str] = mapped_column(String(20), default="3.11")
    dependencies: Mapped[str] = mapped_column(Text, default="")  # One package per line

    # Alerting
    alert_on_failure: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_on_success: Mapped[bool] = mapped_column(Boolean, default=False)

    # Execution settings
    timeout: Mapped[int] = mapped_column(Integer, default=3600)  # seconds
    misfire_grace_time: Mapped[int] = mapped_column(Integer, default=60)  # seconds
    working_directory: Mapped[str] = mapped_column(String(500), default="")
    environment_vars: Mapped[str] = mapped_column(Text, default="")  # JSON format

    # Alert Throttling
    last_alert_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Git tracking
    git_commit: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # Relationships
    executions: Mapped[list["Execution"]] = relationship(
        "Execution",
        back_populates="script",
        cascade="all, delete-orphan",
        order_by="desc(Execution.started_at)",
    )

    def __repr__(self) -> str:
        return f"<Script(id={self.id}, name='{self.name}', enabled={self.enabled})>"

    @property
    def is_managed_by_git(self) -> bool:
        """Check if the script is managed by git."""
        return self.git_commit is not None
