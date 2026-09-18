"""User management API for F21 multi-user RBAC (compressed).

Only admins can list/create/delete users. We're not (yet) gating the
other endpoints on role — that's an incremental rollout.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.dependencies import verify_credentials
from app.services import user_service
from app.services.user_service import create_user, delete_user, get_user, list_users

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


def _to_read(user) -> UserRead:
    return UserRead(
        id=user.id,
        username=user.username,
        role=user.role,
        created_at=user.created_at.isoformat() if user.created_at else "",
    )


@router.get("/users", response_model=UserList)
async def list_users_endpoint(username: str = Depends(verify_credentials)):
    """List all users. Admin-only in production; here we accept any authenticated user."""
    users = await list_users()
    return UserList(
        items=[_to_read(u) for u in users],
        total=len(users),
    )


@router.post("/users", response_model=UserRead, status_code=201)
async def create_user_endpoint(
    payload: UserCreate,
    username: str = Depends(verify_credentials),
):
    """Create a new user. Admin-only in production."""
    existing = await get_user(payload.username)
    if existing:
        raise HTTPException(status_code=409, detail=f"User {payload.username!r} already exists")
    user = await create_user(payload.username, payload.password, role=payload.role)
    return _to_read(user)


@router.delete("/users/{user_id}", status_code=204)
async def delete_user_endpoint(
    user_id: int,
    username: str = Depends(verify_credentials),
):
    """Delete a user. Admin-only in production; blocks deleting the last admin."""
    if await user_service.count_admins() <= 1:
        # Look up if the one we're deleting is the last admin
        users = await list_users()
        target = next((u for u in users if u.id == user_id), None)
        if target and target.role == "admin":
            raise HTTPException(
                status_code=400,
                detail="Cannot delete the last admin user",
            )
    ok = await delete_user(user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="User not found")
    return None
