"""Operator-facing diagnostics endpoint for F19.

GET /api/diagnostics returns a comprehensive one-shot snapshot useful when
triaging an incident. Unlike /health (which is for liveness/readiness probes
and answers "is the service up?"), /api/diagnostics answers "what state is
the service in?".

Sections:
- version: app + python + platform
- process: uptime, PID, RSS, threads
- database: connectivity + table counts
- scheduler: running + job count + job names
- executor: running executions + total subprocesses
- config: sanitized settings snapshot (sensitive fields masked)
- logs: log file path + size + rotation count
"""

from __future__ import annotations

import os
import platform
import time
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app import __version__
from app.api.dependencies import verify_credentials
from app.config import get_settings
from app.database import async_session_maker
from app.models.artifact import Artifact
from app.models.execution import Execution, ExecutionStatus
from app.models.script import Script

router = APIRouter()
settings = get_settings()

# Process start time (module import time) for uptime calculation
_PROCESS_START_TIME = time.monotonic()


@router.get("/diagnostics")
async def get_diagnostics(username: str = Depends(verify_credentials)):
    """Return a comprehensive diagnostic snapshot of the running Cronator instance."""
    import resource

    from app.services.executor import executor_service
    from app.services.scheduler import scheduler_service

    # --- Process info ---
    uptime = time.monotonic() - _PROCESS_START_TIME
    rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux returns KB, macOS returns bytes — normalize
    if platform.system() == "Darwin":
        rss_bytes = rss_kb
    else:
        rss_bytes = rss_kb * 1024

    process_info = {
        "pid": os.getpid(),
        "uptime_seconds": round(uptime, 3),
        "rss_bytes": rss_bytes,
        "rss_mb": round(rss_bytes / (1024 * 1024), 2),
        "thread_count": _thread_count_safe(),
        "python_version": platform.python_version(),
        "platform": f"{platform.system()} {platform.release()} ({platform.machine()})",
    }

    # --- Database ---
    db_info = {
        "reachable": False,
        "script_count": 0,
        "execution_count": 0,
        "running_execution_count": 0,
        "artifact_count": 0,
    }
    try:
        async with async_session_maker() as db:
            db_info["reachable"] = True
            db_info["script_count"] = await db.scalar(select(func.count()).select_from(Script)) or 0
            db_info["execution_count"] = (
                await db.scalar(select(func.count()).select_from(Execution)) or 0
            )
            db_info["running_execution_count"] = (
                await db.scalar(
                    select(func.count())
                    .select_from(Execution)
                    .where(Execution.status == ExecutionStatus.RUNNING.value)
                )
                or 0
            )
            db_info["artifact_count"] = (
                await db.scalar(select(func.count()).select_from(Artifact)) or 0
            )
    except Exception as e:
        db_info["error"] = f"{type(e).__name__}: {e}"

    # --- Scheduler ---
    sched_info = {
        "running": False,
        "job_count": 0,
        "jobs": [],
    }
    try:
        sched_info["running"] = bool(scheduler_service.scheduler.running)
        sched_info["job_count"] = len(scheduler_service.scheduler.get_jobs())
        sched_info["jobs"] = [
            {
                "id": j.id,
                "name": j.name,
                "next_run": str(j.next_run_time) if j.next_run_time else None,
            }
            for j in scheduler_service.scheduler.get_jobs()
        ]
    except Exception as e:
        sched_info["error"] = f"{type(e).__name__}: {e}"

    # --- Executor ---
    exec_info = {
        "running_executions": 0,
        "total_processes": 0,
        "running_scripts": sorted(executor_service._running_scripts),  # noqa: SLF001
    }
    try:
        exec_info["total_processes"] = len(executor_service.running_processes)
        exec_info["running_executions"] = len(executor_service.running_processes)
    except Exception as e:
        exec_info["error"] = f"{type(e).__name__}: {e}"

    # --- Config (masked) ---
    sensitive_keys = {"smtp_password", "secret_key", "admin_password", "postgresql_password"}
    config_snapshot = {
        "app_name": settings.app_name,
        "host": settings.host,
        "port": settings.port,
        "debug": settings.debug,
        "database_url": _mask_db_url(settings.database_url),
        "smtp_enabled": settings.smtp_enabled,
        "smtp_host": settings.smtp_host,
        "smtp_user": settings.smtp_user,
        "alert_email": settings.alert_email,
        "smtp_password": "***" if settings.smtp_password else "",
        "secret_key": "***" if settings.secret_key else "",
        "default_timeout": settings.default_timeout,
        "max_log_size": settings.max_log_size,
        "max_artifact_size_mb": settings.max_artifact_size_mb,
        "min_free_space_mb": settings.min_free_space_mb,
        "backup_retention_days": getattr(settings, "backup_retention_days", None),
    }
    # Mark any unknown keys as sensitive by default — defense in depth
    for k in list(config_snapshot.keys()):
        if k in sensitive_keys and config_snapshot[k] not in (None, "", "***"):
            config_snapshot[k] = "***"

    # --- Logs ---
    log_dir = Path(settings.logs_dir)
    log_file = log_dir / "cronator.log"
    logs_info = {
        "log_dir": str(log_dir),
        "log_file": str(log_file),
        "exists": log_file.exists(),
        "size_bytes": log_file.stat().st_size if log_file.exists() else 0,
        "rotated_files": (
            sorted(log_file.parent.glob("cronator.log.*")) if log_file.parent.exists() else []
        ),
    }

    return {
        "version": __version__,
        "python_version": platform.python_version(),
        "platform": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "python_implementation": platform.python_implementation(),
        "process": process_info,
        "database": db_info,
        "scheduler": sched_info,
        "executor": exec_info,
        "config": config_snapshot,
        "logs": logs_info,
        "as_of": time.time(),
    }


def _mask_db_url(url: str) -> str:
    """Hide credentials in a SQLAlchemy URL."""
    if not url:
        return ""
    if "@" not in url:
        return url
    # postgresql+asyncpg://user:pass@host/db  →  postgresql+asyncpg://user:***@host/db
    scheme, rest = url.split("://", 1) if "://" in url else ("", url)
    if "@" not in rest:
        return url
    creds, hostpart = rest.split("@", 1)
    if ":" in creds:
        user, _ = creds.split(":", 1)
        creds = f"{user}:***"
    return f"{scheme}://{creds}@{hostpart}"


def _thread_count_safe() -> int:
    try:
        import threading

        return threading.active_count()
    except Exception:
        return -1
