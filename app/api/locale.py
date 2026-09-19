"""i18n / locale endpoints for F15.

Locale preference is stored in the settings DB so it persists across
restarts. The Jinja templates don't have full i18n wired up yet — that
needs a base.html refactor with a translation function. For now we expose
a minimal API surface that the UI can use to switch language.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.settings_service import settings_service

router = APIRouter()


# Catalog of supported locales — the actual translations live in
# app/translations/{locale}.json. We start with English and Russian since
# the existing test suite uses both.
SUPPORTED_LOCALES = [
    {"code": "en", "name": "English"},
    {"code": "ru", "name": "Русский"},
]
SUPPORTED_CODES = {loc["code"] for loc in SUPPORTED_LOCALES}


class LocaleSetRequest(BaseModel):
    locale: str = Field(..., min_length=2, max_length=8, examples=["ru"])


@router.get("/locales")
async def list_locales():
    """List all supported UI locales."""
    return {"locales": SUPPORTED_LOCALES, "default": "en"}


@router.get("/locale")
async def get_locale():
    """Return the user's currently active locale (default: 'en')."""
    locale = await settings_service.get("locale", "en")
    return {"locale": locale}


@router.post(
    "/locale",
    openapi_extra={"requestBody": {"content": {"application/json": {"example": {"locale": "ru"}}}}},
)
async def set_locale(payload: LocaleSetRequest):
    """Set the active locale for the current user (persisted to settings).

    Example request body:
        {"locale": "ru"}
    """
    locale = payload.locale
    if locale not in SUPPORTED_CODES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown locale {locale!r}. Supported: {sorted(SUPPORTED_CODES)}",
        )
    await settings_service.set("locale", locale)
    return {"locale": locale}
