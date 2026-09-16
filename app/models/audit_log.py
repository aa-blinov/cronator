"""ScriptAuditLog model for F11 — audit trail of script mutations."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ScriptAuditLog(Base):
    """One row per changed field on a script.

    We store old/new values as strings so the same table can audit any field
    type (str, int, bool) without per-type columns. Long values are stored in
    `old_value` / `new_value` TEXT.
    """

    __tablename__ = "script_audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    script_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("scripts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    field_name: Mapped[str] = mapped_column(String(64), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by: Mapped[str] = mapped_column(String(255), nullable=False, default="system")
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
    )

    def __repr__(self) -> str:
        return (
            f"<ScriptAuditLog script_id={self.script_id} "
            f"field={self.field_name} changed_by={self.changed_by}>"
        )
