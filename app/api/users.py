"""User management API for F21 multi-user RBAC.

Only admins can list/create/delete users, and — via require_admin in
scripts.py/executions.py/settings.py/pages.py — perform any mutating
action anywhere in the app. Viewers get read-only access everywhere.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.dependencies import require_admin, verify_credentials
from app.services import user_service
from app.services.user_service import (
    create_user,
    delete_user,
    get_user,
    list_user_audit,
    list_users,
    record_user_audit,
    update_user,
    verify_password,
)

router = APIRouter()


class UserRead(BaseModel):
    id: int
    username: str
    role: str
    created_at: str  # ISO string


class UserCreate(BaseModel):
    username: str = Field(..., min_length=2, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    password: str = Field(..., min_length=8, max_length=128)
    role: str = Field(default="viewer", pattern="^(admin|viewer)$")

    model_config = {
        "json_schema_extra": {
            "example": {
                "username": "alice",
                "password": "secure-password-1234",
                "role": "viewer",
            }
        }
    }


class UserList(BaseModel):
    items: list[UserRead]
    total: int


class UserUpdate(BaseModel):
    password: str | None = Field(default=None, min_length=8, max_length=128)
    role: str | None = Field(default=None, pattern="^(admin|viewer)$")

    model_config = {
        "json_schema_extra": {"example": {"role": "admin"}}
    }


class SelfPasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=128)

    model_config = {
        "json_schema_extra": {
            "example": {
                "current_password": "old-password-1234",
                "new_password": "new-secure-password-5678",
            }
        }
    }


class UserAuditEntryRead(BaseModel):
    id: int
    target_username: str
    action: str
    detail: str | None = None
    changed_by: str
    changed_at: str  # ISO string


class UserAuditList(BaseModel):
    items: list[UserAuditEntryRead]
    total: int


def _to_read(user) -> UserRead:
    return UserRead(
        id=user.id,
        username=user.username,
        role=user.role,
        created_at=user.created_at.isoformat() if user.created_at else "",
    )


@router.get("/users", response_model=UserList)
async def list_users_endpoint(username: str = Depends(require_admin)):
    """List all users. Admin-only."""
    users = await list_users()
    return UserList(
        items=[_to_read(u) for u in users],
        total=len(users),
    )


@router.get("/users/audit", response_model=UserAuditList)
async def list_user_audit_endpoint(
    target_username: str | None = None,
    limit: int = 200,
    username: str = Depends(require_admin),
):
    """List user-management audit entries. Admin-only."""
    entries = await list_user_audit(target_username, limit=limit)
    return UserAuditList(
        items=[
            UserAuditEntryRead(
                id=e.id,
                target_username=e.target_username,
                action=e.action,
                detail=e.detail,
                changed_by=e.changed_by,
                changed_at=e.changed_at.isoformat() if e.changed_at else "",
            )
            for e in entries
        ],
        total=len(entries),
    )


@router.post("/users", response_model=UserRead, status_code=201)
async def create_user_endpoint(
    payload: UserCreate,
    username: str = Depends(require_admin),
):
    """Create a new user. Admin-only."""
    existing = await get_user(payload.username)
    if existing:
        raise HTTPException(status_code=409, detail=f"User {payload.username!r} already exists")
    user = await create_user(payload.username, payload.password, role=payload.role)
    await record_user_audit(payload.username, "create", username, detail=f"role={payload.role}")
    return _to_read(user)


@router.patch("/users/{user_id}", response_model=UserRead)
async def update_user_endpoint(
    user_id: int,
    payload: UserUpdate,
    username: str = Depends(require_admin),
):
    """Change a user's password and/or role. Admin-only; blocks demoting
    the last admin (mirrors the delete-last-admin guard below)."""
    if payload.password is None and payload.role is None:
        raise HTTPException(status_code=400, detail="Nothing to update")
    users = await list_users()
    target = next((u for u in users if u.id == user_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    demoting_last_admin = payload.role == "viewer" and target.role == "admin"
    if demoting_last_admin and await user_service.count_admins() <= 1:
        raise HTTPException(
            status_code=400,
            detail="Cannot demote the last admin user",
        )
    old_role = target.role
    user = await update_user(user_id, password=payload.password, role=payload.role)
    if payload.role is not None and payload.role != old_role:
        await record_user_audit(
            user.username, "role_change", username, detail=f"{old_role} -> {payload.role}"
        )
    if payload.password is not None:
        await record_user_audit(user.username, "password_reset", username)
    return _to_read(user)


@router.post("/users/me/password", status_code=204)
async def change_own_password_endpoint(
    payload: SelfPasswordChange,
    username: str = Depends(verify_credentials),
):
    """Self-service password change for the currently authenticated user."""
    user = await get_user(username)
    if user is None:
        raise HTTPException(
            status_code=400,
            detail="This account is set via ADMIN_USERNAME/ADMIN_PASSWORD env "
            "vars and has no password to change here — update the environment "
            "and restart instead",
        )
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    await update_user(user.id, password=payload.new_password)
    await record_user_audit(username, "self_password_change", username)
    return None


@router.delete("/users/{user_id}", status_code=204)
async def delete_user_endpoint(
    user_id: int,
    username: str = Depends(require_admin),
):
    """Delete a user. Admin-only; blocks deleting the last admin."""
    users = await list_users()
    target = next((u for u in users if u.id == user_id), None)
    if target and target.role == "admin" and await user_service.count_admins() <= 1:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete the last admin user",
        )
    ok = await delete_user(user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="User not found")
    if target:
        await record_user_audit(target.username, "delete", username)
    return None
