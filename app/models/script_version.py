"""Script version model for tracking script history."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.script import Script


class ScriptVersion(Base):
    """Model for storing script version history."""

    __tablename__ = "script_versions"

    __table_args__ = (
        Index("idx_script_versions_script_created", "script_id", "created_at"),
        Index("idx_script_versions_script_version", "script_id", "version_number"),
    )

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True)

    # Foreign key to script
    script_id: Mapped[int] = mapped_column(
        ForeignKey("scripts.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Version number (auto-incremented per script)
    version_number: Mapped[int] = mapped_column(nullable=False)

    # Snapshot of script content at this version
    content: Mapped[str] = mapped_column(Text, nullable=False)
    dependencies: Mapped[str] = mapped_column(Text, nullable=False, default="")
    python_version: Mapped[str] = mapped_column(String(20), nullable=False, default="3.11")
    cron_expression: Mapped[str] = mapped_column(String(100), nullable=False, default="0 * * * *")
    timeout: Mapped[int] = mapped_column(nullable=False, default=3600)
    environment_vars: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Version metadata
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    created_by: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    script: Mapped["Script"] = relationship("Script", back_populates="versions")

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"<ScriptVersion(id={self.id}, "
            f"script_id={self.script_id}, "
            f"version={self.version_number})>"
        )
