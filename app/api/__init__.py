"""API routes package."""

from fastapi import APIRouter, Depends

from app.api.dependencies import verify_credentials
from app.api.executions import router as executions_router
from app.api.pages import router as pages_router
from app.api.scripts import router as scripts_router
from app.api.settings import router as settings_router

api_router = APIRouter()

# API routes (All require authentication)
api_router.include_router(
    scripts_router,
    prefix="/api/scripts",
    tags=["scripts"],
    dependencies=[Depends(verify_credentials)],
)
api_router.include_router(
    executions_router,
    prefix="/api/executions",
    tags=["executions"],
    dependencies=[Depends(verify_credentials)],
)
api_router.include_router(
    settings_router,
    prefix="/api/settings",
    tags=["settings"],
    dependencies=[Depends(verify_credentials)],
)

# Page routes (HTML)
api_router.include_router(pages_router, tags=["pages"])

__all__ = ["api_router"]
