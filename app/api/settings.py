"""API routes for settings."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import get_settings
from app.services.alerting import alerting_service
from app.services.git_sync import git_sync_service
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
    smtp_use_tls: bool
    alert_email: str

    git_enabled: bool
    git_repo_url: str
    git_branch: str
    git_sync_interval: int
    git_scripts_subdir: str

    default_timeout: int


class GitStatus(BaseModel):
    """Git sync status."""

    enabled: bool
    repo_url: str
    branch: str
    current_commit: str | None
    sync_interval: int
    repo_cloned: bool


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
    smtp_use_tls = await settings_service.get("smtp_use_tls", settings.smtp_use_tls)
    alert_email = await settings_service.get("alert_email", settings.alert_email)
    git_enabled = await settings_service.get("git_enabled", settings.git_enabled)
    git_repo_url = await settings_service.get("git_repo_url", settings.git_repo_url)
    git_branch = await settings_service.get("git_branch", settings.git_branch)
    git_sync_interval = await settings_service.get("git_sync_interval", settings.git_sync_interval)
    git_scripts_subdir = await settings_service.get(
        "git_scripts_subdir", settings.git_scripts_subdir
    )
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
        smtp_use_tls=smtp_use_tls,
        alert_email=alert_email,
        git_enabled=git_enabled,
        git_repo_url=git_repo_url,
        git_branch=git_branch,
        git_sync_interval=git_sync_interval,
        git_scripts_subdir=git_scripts_subdir,
        default_timeout=default_timeout,
    )


@router.get("/git-status")
async def get_git_status() -> GitStatus:
    """Get git sync status."""
    status = git_sync_service.get_status()
    return GitStatus(**status)


@router.post("/git-sync")
async def trigger_git_sync():
    """Manually trigger git sync."""
    success, message = await git_sync_service.sync()

    if not success:
        return {"success": False, "message": message}

    # Reload scheduler jobs after sync
    await scheduler_service.reload_all_jobs()

    return {"success": True, "message": message}


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

    return {"success": sent, "message": "Test email sent" if sent else "Failed to send test email"}


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
    smtp_use_tls: bool | None = None
    alert_email: str | None = None

    git_enabled: bool | None = None
    git_repo_url: str | None = None
    git_branch: str | None = None
    git_token: str | None = None
    git_sync_interval: int | None = None
    git_scripts_subdir: str | None = None

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
    if request.smtp_use_tls is not None:
        updates["smtp_use_tls"] = request.smtp_use_tls
    if request.alert_email is not None:
        updates["alert_email"] = request.alert_email
    if request.git_enabled is not None:
        updates["git_enabled"] = request.git_enabled
    if request.git_repo_url is not None:
        updates["git_repo_url"] = request.git_repo_url
    if request.git_branch is not None:
        updates["git_branch"] = request.git_branch
    if request.git_token is not None:
        updates["git_token"] = request.git_token
    if request.git_sync_interval is not None:
        updates["git_sync_interval"] = request.git_sync_interval
    if request.git_scripts_subdir is not None:
        updates["git_scripts_subdir"] = request.git_scripts_subdir
    if request.default_timeout is not None:
        updates["default_timeout"] = request.default_timeout

    # Save to database
    await settings_service.bulk_set(updates)

    # Reinitialize services with new settings
    # Services will read from settings_service

    return {"success": True, "message": "Settings updated successfully"}
