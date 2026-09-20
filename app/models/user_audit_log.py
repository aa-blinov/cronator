"""UserAuditLog model: audit trail for user-management actions.

Separate from ScriptAuditLog (app/models/audit_log.py) because that
table's script_id is a NOT NULL FK — it has no concept of "no script
involved". User-management events (create/delete/role change/password
reset/self password change) are discrete actions, not per-field diffs,
so this uses an `action` + free-text `detail` shape instead of the
old_value/new_value column pair.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UserAuditLog(Base):
    __tablename__ = "user_audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_username: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by: Mapped[str] = mapped_column(String(255), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
    )

    def __repr__(self) -> str:
        return (
            f"<UserAuditLog target={self.target_username} "
            f"action={self.action} changed_by={self.changed_by}>"
        )
