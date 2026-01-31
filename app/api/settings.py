"""API routes for settings."""

import shutil

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from app.config import get_settings
from app.database import async_session_maker
from app.models.artifact import Artifact
from app.models.execution import Execution
from app.services.alerting import alerting_service
from app.services.scheduler import scheduler_service
from app.services.settings_service import settings_service

router = APIRouter()
settings = get_settings()


class SettingsResponse(BaseModel):
    """Current settings response."""

    app_name: str
    scripts_dir: str
    envs_dir: str

    smtp_enabled: bool
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_from: str
    alert_email: str

    default_timeout: int


class SchedulerStatus(BaseModel):
    """Scheduler status."""

    running: bool
    job_count: int
    jobs: list[dict]


@router.get("")
async def get_settings_info() -> SettingsResponse:
    """Get current settings (non-sensitive)."""
    # Get runtime settings from DB, fallback to env
    smtp_enabled = await settings_service.get("smtp_enabled", settings.smtp_enabled)
    smtp_host = await settings_service.get("smtp_host", settings.smtp_host)
    smtp_port = await settings_service.get("smtp_port", settings.smtp_port)
    smtp_user = await settings_service.get("smtp_user", settings.smtp_user)
    smtp_from = await settings_service.get("smtp_from", settings.smtp_from)
    alert_email = await settings_service.get("alert_email", settings.alert_email)
    default_timeout = await settings_service.get("default_timeout", settings.default_timeout)

    return SettingsResponse(
        app_name=settings.app_name,
        scripts_dir=str(settings.scripts_dir),
        envs_dir=str(settings.envs_dir),
        smtp_enabled=smtp_enabled,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        smtp_user=smtp_user,
        smtp_from=smtp_from,
        alert_email=alert_email,
        default_timeout=default_timeout,
    )


@router.get("/scheduler-status")
async def get_scheduler_status() -> SchedulerStatus:
    """Get scheduler status."""
    jobs = scheduler_service.get_all_jobs_info()
    return SchedulerStatus(
        running=scheduler_service.scheduler.running,
        job_count=len(jobs),
        jobs=jobs,
    )


@router.post("/test-email")
async def test_email():
    """Send a test email."""
    success, message = await alerting_service.test_connection()

    if not success:
        return {"success": False, "message": message}

    # Try sending a real test email
    sent = await alerting_service.send_email(
        subject="[Cronator] Test Email",
        body_html="<h1>Test Email</h1><p>If you received this, email alerts are working!</p>",
        body_text="Test Email\n\nIf you received this, email alerts are working!",
    )

    if not sent:
        # Get the last error from logs or return generic message
        return {"success": False, "message": "SMTP authentication failed. Check your credentials."}

    return {"success": True, "message": "Test email sent successfully"}


@router.post("/reload-scheduler")
async def reload_scheduler():
    """Reload all scheduler jobs from database."""
    await scheduler_service.reload_all_jobs()
    jobs = scheduler_service.get_all_jobs_info()
    return {"message": "Scheduler reloaded", "job_count": len(jobs)}


@router.get("/download-db")
async def download_db():
    """Download the current database file."""
    import os
    import time

    from fastapi.responses import FileResponse

    db_path = settings.database_url.replace("sqlite+aiosqlite:///", "")
    if not os.path.exists(db_path):
        # Try to find it relative to base_dir
        db_path = settings.data_dir / "cronator.db"

    if os.path.exists(db_path):
        return FileResponse(
            path=db_path,
            filename=f"cronator_backup_{int(time.time())}.db",
            media_type="application/x-sqlite3",
        )
    return {"error": "Database file not found"}


class UpdateSettingsRequest(BaseModel):
    """Request to update settings."""

    smtp_enabled: bool | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    alert_email: str | None = None

    default_timeout: int | None = None


@router.post("/update")
async def update_settings(request: UpdateSettingsRequest):
    """Update settings in database."""
    # Collect updates
    updates = {}

    if request.smtp_enabled is not None:
        updates["smtp_enabled"] = request.smtp_enabled
    if request.smtp_host is not None:
        updates["smtp_host"] = request.smtp_host
    if request.smtp_port is not None:
        updates["smtp_port"] = request.smtp_port
    if request.smtp_user is not None:
        updates["smtp_user"] = request.smtp_user
    if request.smtp_password is not None:
        updates["smtp_password"] = request.smtp_password
    if request.smtp_from is not None:
        updates["smtp_from"] = request.smtp_from
    if request.alert_email is not None:
        updates["alert_email"] = request.alert_email
    if request.default_timeout is not None:
        updates["default_timeout"] = request.default_timeout

    # Save to database
    await settings_service.bulk_set(updates)

    # Reinitialize services with new settings
    # Services will read from settings_service

    return {"success": True, "message": "Settings updated successfully"}


@router.get("/artifacts-stats")
async def get_artifacts_stats():
    """Get statistics about artifacts storage."""
    async with async_session_maker() as db:
        # Total artifacts count and size
        result = await db.execute(
            select(
                func.count(Artifact.id).label("total_artifacts"),
                func.sum(Artifact.size_bytes).label("total_size_bytes"),
            )
        )
        row = result.one()
        total_artifacts = row.total_artifacts or 0
        total_size_bytes = row.total_size_bytes or 0

        # Count executions with artifacts
        result = await db.execute(
            select(func.count(Execution.id)).where(Execution.artifacts_count > 0)
        )
        executions_with_artifacts = result.scalar() or 0

    # Get disk usage
    artifacts_dir = settings.artifacts_dir
    try:
        stat = shutil.disk_usage(artifacts_dir if artifacts_dir.exists() else settings.data_dir)
        free_space_bytes = stat.free
        total_space_bytes = stat.total
    except Exception:
        free_space_bytes = 0
        total_space_bytes = 0

    return {
        "total_artifacts": total_artifacts,
        "total_size_bytes": total_size_bytes,
        "total_size_mb": round(total_size_bytes / (1024 * 1024), 2),
        "executions_with_artifacts": executions_with_artifacts,
        "free_space_bytes": free_space_bytes,
        "free_space_mb": round(free_space_bytes / (1024 * 1024), 2),
        "total_space_bytes": total_space_bytes,
        "total_space_mb": round(total_space_bytes / (1024 * 1024), 2),
    }


@router.post("/clear-artifacts")
async def clear_all_artifacts():
    """Delete all artifacts from database and filesystem."""
    import logging

    async with async_session_maker() as db:
        # Get count before deletion
        result = await db.execute(select(func.count(Artifact.id)))
        artifacts_count = result.scalar() or 0

        # Delete all artifacts from database
        result = await db.execute(select(Artifact))
        artifacts = result.scalars().all()

        for artifact in artifacts:
            await db.delete(artifact)

        # Reset all execution counters
        result = await db.execute(select(Execution).where(Execution.artifacts_count > 0))
        executions = result.scalars().all()

        for execution in executions:
            execution.artifacts_count = 0
            execution.artifacts_size_bytes = 0

        await db.commit()

    # Delete artifacts directory from filesystem
    artifacts_dir = settings.artifacts_dir
    deleted_dirs = 0

    if artifacts_dir.exists():
        try:
            # Delete all subdirectories
            for subdir in artifacts_dir.iterdir():
                if subdir.is_dir():
                    shutil.rmtree(subdir)
                    deleted_dirs += 1
        except Exception as e:
            logging.error(f"Failed to delete artifacts directory: {e}")

    return {
        "success": True,
        "message": f"Deleted {artifacts_count} artifacts from {deleted_dirs} executions",
        "deleted_artifacts": artifacts_count,
        "deleted_directories": deleted_dirs,
    }
