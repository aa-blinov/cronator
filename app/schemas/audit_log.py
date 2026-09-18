"""Pydantic schemas for ScriptAuditLog."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class AuditEntryRead(BaseModel):
    """One row in the script audit log."""

    id: int
    script_id: int
    field_name: str
    old_value: str | None = None
    new_value: str | None = None
    changed_by: str
    changed_at: datetime

    model_config = {"from_attributes": True}


class AuditLogList(BaseModel):
    """List of audit entries with pagination."""

    items: list[AuditEntryRead]
    total: int
    page: int
    per_page: int
    pages: int
