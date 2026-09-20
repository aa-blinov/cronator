"""API routes for settings."""

import shutil
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.dependencies import require_admin
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

    # F16: UI theme (daisyUI theme name)
    theme: str = "dim"

    # F17: Webhook URL for failure notifications
    webhook_url: str = ""

    # P0: automated database backup toggle
    auto_backup_enabled: bool = False


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
    theme = await settings_service.get("theme", "dim")
    webhook_url = await settings_service.get("webhook_url", "")
    auto_backup_enabled = await settings_service.get("auto_backup_enabled", False)

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
        theme=theme,
        webhook_url=webhook_url,
        auto_backup_enabled=auto_backup_enabled,
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
async def test_email(username: str = Depends(require_admin)):
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
async def reload_scheduler(username: str = Depends(require_admin)):
    """Reload all scheduler jobs from database."""
    await scheduler_service.reload_all_jobs()
    jobs = scheduler_service.get_all_jobs_info()
    return {"message": "Scheduler reloaded", "job_count": len(jobs)}


@router.get("/download-db")
async def download_db(username: str = Depends(require_admin)):
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

    # F16: UI theme — daisyUI theme name (dim / light / cupcake / ...)
    theme: str | None = Field(default=None, pattern="^(dim|light|cupcake|dracula|business)$")

    # F17: webhook URL for failure notifications
    webhook_url: str | None = None

    # P0: automated database backup, off by default — an operator opts in
    # once they've confirmed the backups directory is on persistent,
    # backed-up storage (see docs/OPERATIONS.md).
    auto_backup_enabled: bool | None = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "smtp_enabled": True,
                "smtp_host": "smtp.gmail.com",
                "smtp_port": 587,
                "smtp_user": "alerts@example.com",
                "smtp_password": "app-specific-password",
                "smtp_from": "cronator@example.com",
                "alert_email": "oncall@example.com",
                "default_timeout": 3600,
                "theme": "dim",
            }
        }
    }


@router.post("/update")
async def update_settings(request: UpdateSettingsRequest, username: str = Depends(require_admin)):
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
    if request.theme is not None:
        updates["theme"] = request.theme
    if request.webhook_url is not None:
        updates["webhook_url"] = request.webhook_url
    if request.auto_backup_enabled is not None:
        updates["auto_backup_enabled"] = request.auto_backup_enabled

    # Save to database
    await settings_service.bulk_set(updates)

    # Reinitialize services with new settings
    # Services will read from settings_service

    return {"success": True, "message": "Settings updated successfully"}


def _get_disk_free_total(path) -> tuple[int, int]:
    """Get free and total disk space (blocking, runs in thread)."""
    try:
        disk = shutil.disk_usage(path)
        return disk.free, disk.total
    except Exception:
        return 0, 0


@router.get("/artifacts-stats")
async def get_artifacts_stats():
    """Get statistics about artifacts storage."""
    import asyncio

    async with async_session_maker() as db:
        # Total artifacts count and DB-recorded size (written at artifact creation time)
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

    # disk_usage is a single fast syscall — still offload to thread to be safe
    artifacts_dir = settings.artifacts_dir
    check_path = artifacts_dir if artifacts_dir.exists() else settings.data_dir
    free_space_bytes, total_space_bytes = await asyncio.to_thread(_get_disk_free_total, check_path)

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


@router.get("/execution-stats")
async def get_execution_stats():
    """Get execution history statistics for the settings page."""
    from app.services.cleanup_service import cleanup_service

    return await cleanup_service.get_execution_stats()


@router.post("/cleanup-executions")
async def cleanup_executions(days: int = 90, username: str = Depends(require_admin)):
    """Delete all executions older than `days` days (excluding running ones)."""
    if days < 1 or days > 3650:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="days must be between 1 and 3650")

    from app.services.cleanup_service import cleanup_service

    result = await cleanup_service.cleanup_older_than_days(days)
    return {
        "success": True,
        "message": (f"Deleted {result['deleted_executions']} executions older than {days} days"),
        "deleted_executions": result["deleted_executions"],
        "deleted_artifact_dirs": result["deleted_artifact_dirs"],
    }


@router.post("/clear-artifacts")
async def clear_all_artifacts(username: str = Depends(require_admin)):
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


# ---------------------------------------------------------------------------
# F12: Backup / Restore from UI
# ---------------------------------------------------------------------------


@router.get("/backups")
async def list_available_backups():
    """List backup files available in the host's backups directory."""
    from pathlib import Path

    backups_dir = Path("/app/backups") if Path("/app").exists() else Path("./backups")
    if not backups_dir.exists():
        # Fallback: scan the same dir as the docker-entrypoint uses
        backups_dir = Path(settings.data_dir).parent / "backups"

    files: list[dict] = []
    if backups_dir.exists():
        for p in sorted(backups_dir.glob("*.sql.gz"), reverse=True):
            try:
                stat = p.stat()
                files.append(
                    {
                        "filename": p.name,
                        "size_bytes": stat.st_size,
                        "created_at": stat.st_mtime,
                    }
                )
            except OSError:
                continue

    return {"backups": files, "backups_dir": str(backups_dir)}


@router.post("/restore-backup")
async def restore_backup(file: UploadFile = File(...), username: str = Depends(require_admin)):
    """Restore from a user-uploaded .sql.gz backup file (F12).

    The upload is validated, decompressed, and applied via the database
    connection. We do NOT spawn a separate subprocess — that requires psql on
    PATH which isn't always available inside the application container.
    Instead we use SQLAlchemy core to apply each statement.
    """
    import gzip
    import logging
    import re
    from pathlib import Path

    from sqlalchemy import text

    logger = logging.getLogger(__name__)

    # Validate filename
    if not file.filename or not file.filename.endswith(".sql.gz"):
        raise HTTPException(
            status_code=400,
            detail="Invalid filename: must be a .sql.gz file",
        )

    # Save to a temp file (StreamingUploadFile may be too large for memory)
    import tempfile

    tmpdir = Path(tempfile.mkdtemp(prefix="crinator-restore-"))
    tmp_path = tmpdir / file.filename
    try:
        content = await file.read()
        if len(content) > 500 * 1024 * 1024:  # 500 MB cap
            raise HTTPException(status_code=413, detail="Backup file too large (>500 MB)")
        tmp_path.write_bytes(content)

        # Decompress
        try:
            sql_bytes = gzip.decompress(content)
        except (OSError, EOFError, gzip.BadGzipFile) as e:
            raise HTTPException(status_code=400, detail=f"Invalid gzip file: {e}") from e

        sql_text = sql_bytes.decode("utf-8", errors="replace")

        # Block obviously dangerous statements (defense in depth — caller should
        # know what they're doing, but DROP DATABASE on the live db would be
        # catastrophic). We don't have a sandbox, so we refuse destructive
        # commands outright.
        dangerous = re.findall(
            r"\b(DROP\s+DATABASE|DROP\s+SCHEMA|TRUNCATE\s+pg_catalog)\b",
            sql_text,
            flags=re.IGNORECASE,
        )
        if dangerous:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Backup contains destructive statements that would target "
                    "system catalogs: " + ", ".join(sorted(set(dangerous)))
                ),
            )

        # Apply via the application's existing async engine — no extra
        # dependency on psycopg2 (which isn't installed in the runtime image)
        # and each plain SQL statement commits independently in its own
        # transaction. pg_dump's data section is COPY ... FROM stdin, not
        # INSERTs — a plain `;\n` split tears the COPY header away from its
        # data and sends it through db.execute(), which either hangs the
        # connection waiting for COPY-protocol data that never arrives, or
        # (once the header/data split lands on a lucky boundary) silently
        # drops every row while still reporting "success". COPY blocks need
        # their own path via asyncpg's copy_to_table.
        import io

        from app.database import async_session_maker

        copy_header_re = re.compile(
            r"^COPY\s+([^\s(]+)\s*(?:\(([^)]*)\))?\s+FROM\s+stdin;\s*$",
            re.IGNORECASE,
        )

        statements_applied = 0
        rows_restored = 0
        failed = 0
        lines = sql_text.split("\n")
        n = len(lines)
        async with async_session_maker() as db:
            buf: list[str] = []

            async def flush_buf() -> None:
                nonlocal statements_applied, failed
                stmt = "\n".join(buf).strip()
                buf.clear()
                if not stmt:
                    return
                try:
                    await db.execute(text(stmt))
                    await db.commit()
                    statements_applied += 1
                except Exception as e:
                    logger.warning(f"Statement failed (skipped): {e}")
                    await db.rollback()
                    failed += 1

            i = 0
            try:
                while i < n:
                    line = lines[i]
                    match = copy_header_re.match(line.strip())
                    if match:
                        await flush_buf()
                        table = match.group(1)
                        schema_name, _, table_name = table.rpartition(".")
                        data_lines: list[str] = []
                        i += 1
                        while i < n and lines[i] != "\\.":
                            data_lines.append(lines[i])
                            i += 1
                        i += 1  # skip the `\.` terminator line
                        data_text = "\n".join(data_lines)
                        if data_text:
                            try:
                                conn = await db.connection()
                                adapted = await conn.get_raw_connection()
                                result = await adapted.driver_connection.copy_to_table(
                                    table_name,
                                    schema_name=schema_name or None,
                                    source=io.BytesIO((data_text + "\n").encode("utf-8")),
                                    format="text",
                                )
                                rows_restored += int((result or "COPY 0").rsplit(" ", 1)[-1])
                                statements_applied += 1
                            except Exception as e:
                                logger.warning(f"COPY into {table} failed (skipped): {e}")
                                failed += 1
                        continue
                    buf.append(line)
                    if line.rstrip().endswith(";"):
                        await flush_buf()
                    i += 1
                await flush_buf()
            finally:
                # pg_dump sets search_path to '' for the whole session (not
                # just the current transaction) so every object in the dump
                # is forced to be schema-qualified. Left as-is, that empty
                # search_path rides back to the connection pool with this
                # session and breaks the next unrelated request that
                # happens to reuse it — any unqualified `FROM some_table`
                # would 500 with "relation does not exist" until that pooled
                # connection is eventually recycled.
                try:
                    await db.execute(text("RESET search_path"))
                    await db.commit()
                except Exception:
                    logger.exception("Failed to reset search_path after restore")

        return {
            "success": failed == 0,
            "statements_applied": statements_applied,
            "statements_failed": failed,
            "rows_restored": rows_restored,
            "filename": file.filename,
            "message": (
                f"Restored {statements_applied} statements ({rows_restored} rows) "
                f"from {file.filename}"
                + (f", {failed} statement(s) failed" if failed else "")
                + ". Note: in-flight executions may need to be cancelled."
            ),
        }
    finally:
        # Cleanup temp files
        try:
            tmp_path.unlink(missing_ok=True)
            tmpdir.rmdir()
        except OSError:
            pass


# F17: Webhook test endpoint
@router.post(
    "/test-webhook",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {"example": {"webhook_url": "https://example.com/webhook"}}
            }
        }
    },
)
async def test_webhook(payload: dict | None = None, username: str = Depends(require_admin)):
    """Send a test payload to the configured webhook URL (from body or stored setting)."""
    import httpx

    body = payload or {}
    target = body.get("webhook_url") or (await settings_service.get("webhook_url", ""))
    if not target:
        raise HTTPException(status_code=400, detail="No webhook_url configured")

    payload = {
        "type": "test",
        "app": "Cronator",
        "message": "This is a test webhook from Cronator",
        "timestamp": datetime.now(UTC).isoformat(),
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(target, json=payload)
        return {
            "success": True,
            "status_code": r.status_code,
            "message": f"Webhook returned {r.status_code}",
        }
    except Exception as e:
        return {"success": False, "message": f"{type(e).__name__}: {e}"}
