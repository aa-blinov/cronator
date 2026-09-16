"""User model for F21 — minimal multi-user RBAC.

We use a single role enum ('admin' | 'viewer'). Passwords are hashed with
PBKDF2-HMAC-SHA256 (stdlib, no extra dependency). The 'admin' role can
manage users; 'viewer' has the same access to scripts/executions as before
for now — incremental rollout.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="viewer")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    def __repr__(self) -> str:
        return f"<User {self.username} ({self.role})>"
