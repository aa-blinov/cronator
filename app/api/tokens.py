"""API token management routes.

Every route takes require_admin — the middleware-level include also has
verify_credentials, so a token holder passes authentication and then the
admin check; the env-defined admin (no User row) passes both, same as
elsewhere in the app.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.dependencies import require_admin
from app.services import api_token_service

router = APIRouter()


class TokenCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100, pattern=r"^[A-Za-z0-9 _-]+$")

    model_config = {"json_schema_extra": {"example": {"name": "nightly-report-ci"}}}


class TokenRead(BaseModel):
    id: int
    name: str
    prefix: str
    created_by: str
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None

    model_config = {"from_attributes": True}


class TokenCreated(TokenRead):
    # Shown exactly once — the hash is what gets stored.
    token: str


@router.get("", response_model=list[TokenRead])
async def list_api_tokens(username: str = Depends(require_admin)):
    return await api_token_service.list_tokens()


@router.post("", response_model=TokenCreated, status_code=status.HTTP_201_CREATED)
async def create_api_token(payload: TokenCreate, username: str = Depends(require_admin)):
    row, plain = await api_token_service.create_token(payload.name.strip(), username)
    return TokenCreated(
        id=row.id,
        name=row.name,
        prefix=row.prefix,
        created_by=row.created_by,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        revoked_at=row.revoked_at,
        token=plain,
    )


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_token(token_id: int, username: str = Depends(require_admin)):
    if not await api_token_service.revoke_token(token_id):
        raise HTTPException(status_code=404, detail="Token not found")
