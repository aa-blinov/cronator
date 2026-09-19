"""Main FastAPI application entry point."""

import logging
import logging.handlers
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from app import __version__
from app.api import api_router
from app.config import get_settings
from app.database import close_db
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.services.metrics import init_app_info
from app.services.scheduler import scheduler_service

settings = get_settings()

# Configure logging
log_dir = settings.logs_dir
log_file = log_dir / "cronator.log"

# Select formatter based on settings.log_format (F20)
from app.services.json_logging import HumanFormatter, JsonFormatter

if settings.log_format.lower() == "json":
    chosen_formatter: logging.Formatter = JsonFormatter()
else:
    chosen_formatter = HumanFormatter()

# Create handlers list - always include StreamHandler
handlers: list[logging.Handler] = [logging.StreamHandler()]

# Try to add file handler, but handle permission errors gracefully
try:
    # Ensure directory exists
    log_dir.mkdir(parents=True, exist_ok=True)
    # Try to create file handler
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
    )
    file_handler.setFormatter(chosen_formatter)
    handlers.append(file_handler)
except (PermissionError, OSError) as e:
    # If we can't write to the log file, just use StreamHandler
    # This allows the app to start even if log directory has permission issues
    import sys

    print(f"Warning: Could not create log file at {log_file}: {e}", file=sys.stderr)
    print("Warning: Logging to file disabled. Using console logging only.", file=sys.stderr)

# Apply formatter to StreamHandler too so JSON output works everywhere
for h in handlers:
    h.setFormatter(chosen_formatter)

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    handlers=handlers,
)
logger = logging.getLogger(__name__)

settings = get_settings()


# Initialize the metrics registry at import time
init_app_info()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle manager."""
    import os

    logger.info("Starting Cronator...")

    # Ensure directories exist
    settings.ensure_directories()

    # Run database migrations with Alembic (skip in tests)
    if not os.getenv("SKIP_ALEMBIC_MIGRATIONS"):
        logger.info("Running database migrations...")
        import subprocess
        import sys

        try:
            # Run alembic upgrade head
            result = subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                check=True,
                capture_output=True,
                text=True,
            )
            logger.info(f"Migrations completed: {result.stdout}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Migration failed: {e.stderr}")
            raise
    else:
        logger.info("Skipping database migrations (SKIP_ALEMBIC_MIGRATIONS is set)")

    logger.info("Database initialized")

    # Initialize settings service and migrate from .env if needed
    from app.services.settings_service import settings_service

    await settings_service.load_from_db()
    migrated = await settings_service.migrate_from_env()
    if migrated > 0:
        logger.info(f"Migrated {migrated} settings from .env to database")

    # Seed default admin user from env vars if no users exist yet (F21 RBAC)
    from app.services.user_service import ensure_admin_seeded

    await ensure_admin_seeded()

    # Start scheduler
    await scheduler_service.start()
    logger.info("Scheduler started")

    # Cleanup stale executions
    from app.services.executor import executor_service  # noqa: F811

    await executor_service.cleanup_stale_executions()
    logger.info("Stale executions cleaned up")

    # Register all scripts in environment service for coordination
    from sqlalchemy import select

    from app.database import async_session_maker
    from app.models.script import Script
    from app.services.environment import environment_service

    async with async_session_maker() as db:
        result = await db.execute(select(Script))
        scripts = result.scalars().all()
        for script in scripts:
            environment_service.register_script(script.name, script.id)
        logger.info(f"Registered {len(scripts)} scripts in environment service")

    logger.info(f"Cronator is running on http://{settings.host}:{settings.port}")

    yield

    # Shutdown — registered as `app.shutdown` event by uvicorn.
    # Order matters:
    #   1. Stop the scheduler first so no NEW jobs are dispatched during shutdown
    #   2. Cancel all in-flight executions so they finish with status=CANCELLED
    #      rather than being SIGKILL'd by the OS and stuck in RUNNING forever
    #   3. Close the database engine to release connections
    await graceful_shutdown(scheduler_service, executor_service, close_db)


async def graceful_shutdown(scheduler, executor, close_db_fn):
    """Perform a graceful shutdown of all background services.

    Public function (not nested in lifespan) so it can be unit-tested in
    isolation. Idempotent: safe to call twice.
    """
    from app.services.executor import executor_service as _exec_singleton

    logger.info("Shutting down Cronator gracefully...")

    # 1. Stop the scheduler (no new jobs fire)
    try:
        await scheduler.stop()
    except Exception as e:
        logger.warning(f"Error stopping scheduler during shutdown: {e}")

    # 2. Cancel all in-flight executions so they finish with status=CANCELLED
    #    rather than being SIGKILL'd by the OS grace period
    try:
        in_flight = list(executor.running_processes.keys())
        for execution_id in in_flight:
            try:
                await _exec_singleton.cancel_execution(execution_id)
            except Exception as e:
                logger.warning(f"Error cancelling execution {execution_id} during shutdown: {e}")
        if in_flight:
            logger.info(f"Cancelled {len(in_flight)} in-flight execution(s) during shutdown")
    except Exception as e:
        logger.warning(f"Error iterating in-flight executions during shutdown: {e}")

    # 3. Kill any in-flight environment setup (venv creation / pip install).
    #    These aren't tracked in executor.running_processes — that dict only
    #    ever holds a script's own process, never its environment-setup
    #    subprocess — so without this a pip install in progress would be
    #    left running as an orphan after the app exits.
    try:
        from app.services.environment import environment_service

        killed = environment_service.kill_all_processes()
        if killed:
            logger.info(f"Killed {killed} in-flight environment subprocess(es) during shutdown")
    except Exception as e:
        logger.warning(f"Error killing environment subprocesses during shutdown: {e}")

    # 4. Close the database engine
    try:
        await close_db_fn()
    except Exception as e:
        logger.warning(f"Error closing database during shutdown: {e}")

    logger.info("Cronator stopped")


# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    description="Python Script Scheduler with Web UI",
    version=__version__,
    lifespan=lifespan,
)

# Register security headers middleware (must run before exception handlers
# so error responses also carry the headers).
app.add_middleware(SecurityHeadersMiddleware)


@app.get("/metrics", include_in_schema=False)
async def metrics_endpoint():
    """Prometheus text exposition format.

    Updates transient gauges (running executions, scheduler job count,
    script totals) on each scrape so the values reflect the current state.
    """
    from sqlalchemy import func, select

    from app.database import async_session_maker
    from app.models.artifact import Artifact
    from app.models.execution import Execution, ExecutionStatus
    from app.models.script import Script
    from app.services.metrics import (
        get_uptime_seconds,
        metrics_registry,
    )

    # Refresh dynamic gauges
    try:
        async with async_session_maker() as db:
            script_total = await db.scalar(select(func.count()).select_from(Script)) or 0
            running = (
                await db.scalar(
                    select(func.count())
                    .select_from(Execution)
                    .where(Execution.status == ExecutionStatus.RUNNING.value)
                )
                or 0
            )
            artifacts_total = await db.scalar(select(func.count()).select_from(Artifact)) or 0
        metrics_registry.gauge_set("crinator_scripts_total", float(script_total))
        metrics_registry.gauge_set("crinator_executions_running", float(running))
        metrics_registry.gauge_set("crinator_artifacts_total", float(artifacts_total))
    except Exception:
        # Don't fail metrics scrape because of a DB hiccup
        pass

    # Scheduler jobs (in-process, always reachable)
    try:
        from app.services.scheduler import scheduler_service

        job_count = len(scheduler_service.scheduler.get_jobs())
        metrics_registry.gauge_set("crinator_scheduler_jobs", float(job_count))
    except Exception:
        pass

    metrics_registry.gauge_set("crinator_uptime_seconds", get_uptime_seconds())
    init_app_info()

    body = metrics_registry.render()
    return PlainTextResponse(body, media_type="text/plain; version=0.0.4; charset=utf-8")


# Exception handlers for centralized error handling
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle all unhandled exceptions."""
    logger.exception(f"Unhandled exception on {request.url.path}: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Internal server error",
            "type": type(exc).__name__,
            "path": str(request.url.path),
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle validation errors with detailed information."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": "Validation error",
            "errors": exc.errors(),
            "body": exc.body,
        },
    )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    """Handle ValueError as bad request."""
    logger.warning(f"ValueError on {request.url.path}: {exc}")
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": str(exc)},
    )


# Setup templates
templates_dir = Path(__file__).parent / "templates"
app.state.templates = Jinja2Templates(directory=str(templates_dir))


# Add custom Jinja2 filters
def filesizeformat(value):
    """Convert bytes to human-readable file size."""
    try:
        bytes_value = int(value)
    except (ValueError, TypeError):
        return "0 B"

    if bytes_value == 0:
        return "0 B"

    units = ["B", "KB", "MB", "GB", "TB"]
    k = 1024
    i = 0

    while bytes_value >= k and i < len(units) - 1:
        bytes_value /= k
        i += 1

    return f"{bytes_value:.2f} {units[i]}"


app.state.templates.env.filters["filesizeformat"] = filesizeformat

# Setup static files (if needed)
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Include routers
app.include_router(api_router)


@app.get("/health")
async def health_check():
    """Enhanced health check endpoint with detailed status.

    Includes:
    - app metadata: name, version, timestamp
    - components.database: ping result
    - components.scheduler: running flag + job_count
    - components.disk: free/total bytes and percent used on the data directory
    - components.migrations: current/head alembic revisions and pending flag
      (or "skipped" status when SKIP_ALEMBIC_MIGRATIONS=1, e.g. in tests)
    """
    from app import __version__
    from app.database import async_session_maker

    checks: dict = {
        "status": "healthy",
        "app": settings.app_name,
        "version": __version__,
        "timestamp": datetime.now(UTC).isoformat(),
        "components": {
            "database": "unknown",
            "scheduler": {"status": "unknown"},
            "disk": {},
            "migrations": {},
        },
    }

    # Database check
    try:
        async with async_session_maker() as db:
            await db.execute(text("SELECT 1"))
        checks["components"]["database"] = "healthy"
    except Exception as e:
        checks["components"]["database"] = f"unhealthy: {type(e).__name__}"
        checks["status"] = "degraded"
        logger.error(f"Database health check failed: {e}")

    # Scheduler check (status + job_count for operator visibility)
    try:
        is_running = scheduler_service.scheduler.running
        try:
            job_count = len(scheduler_service.scheduler.get_jobs())
        except Exception:
            job_count = 0
        checks["components"]["scheduler"] = {
            "status": "running" if is_running else "stopped",
            "job_count": job_count,
        }
        if not is_running:
            checks["status"] = "degraded"
    except Exception as e:
        checks["components"]["scheduler"] = {
            "status": f"error: {type(e).__name__}",
            "job_count": 0,
        }
        checks["status"] = "degraded"
        logger.error(f"Scheduler health check failed: {e}")

    # Disk usage on the data directory (where artifacts/logs/backups accumulate)
    try:
        import shutil

        # Fall back to a directory that always exists if data_dir doesn't exist yet
        # (e.g. in fresh test fixtures). The point is to report useful disk info,
        # not to fail health checks.
        target = settings.data_dir if settings.data_dir.exists() else Path("/")
        usage = shutil.disk_usage(target)
        total = usage.total
        free = usage.free
        used = usage.used
        used_percent = round((used / total) * 100, 1) if total else 0.0
        checks["components"]["disk"] = {
            "path": str(target),
            "total_bytes": total,
            "total_mb": round(total / (1024 * 1024), 2),
            "free_bytes": free,
            "free_mb": round(free / (1024 * 1024), 2),
            "used_bytes": used,
            "used_percent": used_percent,
        }
        # Warn (but don't mark degraded) at 95% full — operators should still see
        # the app as functional, but it's actionable info.
        if used_percent >= 95:
            checks["components"]["disk"]["warning"] = (
                f"disk is {used_percent}% full — clean up artifacts or extend storage"
            )
    except Exception as e:
        # Disk info is informational only — never degrades app health.
        checks["components"]["disk"] = {"error": f"{type(e).__name__}: {e}"}

    # Migrations status (best-effort; tests skip alembic and don't have the table)
    try:
        import os

        if os.getenv("SKIP_ALEMBIC_MIGRATIONS"):
            checks["components"]["migrations"] = {
                "status": "skipped",
                "reason": "SKIP_ALEMBIC_MIGRATIONS=1",
            }
        else:
            from alembic.config import Config
            from alembic.runtime.migration import MigrationContext
            from alembic.script import ScriptDirectory
            from sqlalchemy import create_engine

            cfg = Config("alembic.ini")
            script_dir = ScriptDirectory.from_config(cfg)
            head_rev = script_dir.get_current_head()

            # Alembic's MigrationContext needs a sync Connection.
            # Use a sync engine derived from the async one to inspect migrations.
            from app.database import engine as _async_engine

            sync_url = _async_engine.url.render_as_string(hide_password=False)
            # Strip async driver suffix to get sync URL
            sync_url = sync_url.replace("+asyncpg", "").replace("+aiosqlite", "")
            try:
                sync_engine = create_engine(sync_url)
            except ModuleNotFoundError as exc:
                # e.g. psycopg2 not installed for PostgreSQL sync URL — skip silently
                checks["components"]["migrations"] = {
                    "status": "unavailable",
                    "reason": f"sync driver not installed ({exc.name})",
                    "head": head_rev,
                }
            else:
                try:
                    with sync_engine.connect() as conn:
                        ctx = MigrationContext.configure(conn)
                        current_rev = ctx.get_current_revision()
                finally:
                    sync_engine.dispose()

                pending = current_rev != head_rev
                checks["components"]["migrations"] = {
                    "status": "ok" if not pending else "pending",
                    "current": current_rev,
                    "head": head_rev,
                    "pending": pending,
                }
                if pending:
                    checks["status"] = "degraded"
    except Exception as e:
        checks["components"]["migrations"] = {
            "status": "error",
            "error": f"{type(e).__name__}: {e}",
        }  # noqa: E501

    # Return 503 if any component is degraded
    status_code = 200 if checks["status"] == "healthy" else 503
    return JSONResponse(content=checks, status_code=status_code)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
