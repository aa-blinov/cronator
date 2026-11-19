"""Server-side login sessions (the cookie-based login flow).

Basic Auth moved the credentials into the browser's own popup and kept
them there for the whole browser lifetime: no visible "you are logged in
as", no logout button, and the only way out was closing every window.
These sessions are what /login sets and /logout clears — a signed-in
user carries a token cookie; the server stores only the SHA-256 hash of
the token, so a database dump cannot be replayed as sessions.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.username", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # SHA-256 of the bearer token; the raw token exists only in the user's
    # cookie (the same trade the users table makes with password hashes).
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def is_expired(self) -> bool:
        return datetime.now(UTC) >= self.expires_at

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<AuthSession {self.username} expires {self.expires_at}>"
