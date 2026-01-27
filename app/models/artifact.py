"""Artifact model for execution file artifacts."""

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base


class Artifact(Base):
    """Model for file artifacts created during script execution."""

    __tablename__ = "artifacts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    execution_id = Column(Integer, ForeignKey("executions.id", ondelete="CASCADE"), nullable=False)
    
    # Stored filename (unique timestamped name on disk)
    filename = Column(String(255), nullable=False)
    
    # Original filename provided by user
    original_filename = Column(String(255), nullable=False)
    
    # File size in bytes
    size_bytes = Column(Integer, nullable=False, default=0)
    
    # When the artifact was created
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))

    # Relationships
    execution = relationship("Execution", back_populates="artifacts")

    # Indexes for performance
    __table_args__ = (
        Index("idx_artifact_execution", "execution_id"),
        Index("idx_artifact_created", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Artifact(id={self.id}, execution_id={self.execution_id}, filename='{self.filename}')>"
