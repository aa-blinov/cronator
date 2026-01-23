"""API routes for settings."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import get_settings
from app.services.alerting import alerting_service
from app.services.git_sync import git_sync_service
from app.services.scheduler import scheduler_service

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
    return SettingsResponse(
        app_name=settings.app_name,
        scripts_dir=str(settings.scripts_dir),
        envs_dir=str(settings.envs_dir),
        smtp_enabled=settings.smtp_enabled,
        smtp_host=settings.smtp_host,
        smtp_port=settings.smtp_port,
        smtp_user=settings.smtp_user,
        smtp_from=settings.smtp_from,
        smtp_use_tls=settings.smtp_use_tls,
        alert_email=settings.alert_email,
        git_enabled=settings.git_enabled,
        git_repo_url=settings.git_repo_url,
        git_branch=settings.git_branch,
        git_sync_interval=settings.git_sync_interval,
        git_scripts_subdir=settings.git_scripts_subdir,
        default_timeout=settings.default_timeout,
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
            media_type="application/x-sqlite3"
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
    git_sync_interval: int | None = None
    git_scripts_subdir: str | None = None
    
    default_timeout: int | None = None


@router.post("/update")
async def update_settings(request: UpdateSettingsRequest):
    """Update settings in .env file."""
    from pathlib import Path
    
    env_path = Path(".env")
    if not env_path.exists():
        raise HTTPException(status_code=404, detail=".env file not found")
    
    # Read current .env
    with open(env_path, encoding="utf-8") as f:
        lines = f.readlines()
    
    # Update values
    updates = {
        "SMTP_ENABLED": request.smtp_enabled,
        "SMTP_HOST": request.smtp_host,
        "SMTP_PORT": request.smtp_port,
        "SMTP_USER": request.smtp_user,
        "SMTP_PASSWORD": request.smtp_password,
        "SMTP_FROM": request.smtp_from,
        "SMTP_USE_TLS": request.smtp_use_tls,
        "ALERT_EMAIL": request.alert_email,
        "GIT_ENABLED": request.git_enabled,
        "GIT_REPO_URL": request.git_repo_url,
        "GIT_BRANCH": request.git_branch,
        "GIT_SYNC_INTERVAL": request.git_sync_interval,
        "GIT_SCRIPTS_SUBDIR": request.git_scripts_subdir,
        "DEFAULT_TIMEOUT": request.default_timeout,
    }
    
    # Filter out None values
    updates = {k: v for k, v in updates.items() if v is not None}
    
    # Update lines
    new_lines = []
    updated_keys = set()
    
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                value = updates[key]
                if isinstance(value, bool):
                    value = "true" if value else "false"
                new_lines.append(f"{key}={value}\n")
                updated_keys.add(key)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)
    
    # Add new keys that weren't in the file
    for key, value in updates.items():
        if key not in updated_keys:
            if isinstance(value, bool):
                value = "true" if value else "false"
            new_lines.append(f"{key}={value}\n")
    
    # Write back
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
    
    # Reload settings
    get_settings(reload=True)
    
    # Reload services
    from app.services.alerting import alerting_service
    from app.services.git_sync import git_sync_service
    
    # Reinitialize services with new settings
    alerting_service.__init__()
    git_sync_service.__init__()
    
    return {"success": True, "message": "Settings updated successfully"}
