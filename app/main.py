"""Main FastAPI application entry point."""

import logging
import logging.handlers
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import GZipMiddleware

from app import __version__
from app.api import api_router
from app.api.auth import router as auth_router
from app.config import get_settings
from app.database import close_db
from app.middleware.csrf_origin_guard import CsrfOriginGuardMiddleware
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

# uvicorn's CLI (`uvicorn app.main:app`) configures its own "uvicorn",
# "uvicorn.error" and "uvicorn.access" loggers *before* this module is
# imported, each with propagate=False and uvicorn's own plain-text
# handler. Without this, HTTP access lines (status code, path, latency —
# exactly what a log aggregator wants) never reach cronator.log and are
# never JSON-formatted even when LOG_FORMAT=json, regardless of anything
# configured above. Point them at the same handlers instead.
for _uvicorn_logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
    _uvicorn_logger = logging.getLogger(_uvicorn_logger_name)
    _uvicorn_logger.handlers = handlers
    _uvicorn_logger.propagate = False

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

    # Wait for the database to become reachable before migrating. On a cold
    # container start the DB hostname may not resolve yet ("Temporary failure
    # in name resolution"), which used to surface as unhandled 500s on the
    # first requests instead of a clean, retried startup.
    await wait_for_database()

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

    # Drift detection: warn (don't fail) if the schema is behind Alembic head.
    migration_status = await get_migration_status()
    if migration_status.get("pending"):
        logger.warning(
            "Database schema is behind Alembic head "
            f"(current={migration_status.get('current')!r}, "
            f"head={migration_status.get('head')!r}) — run `alembic upgrade head`"
        )

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

    # Re-encrypt plaintext environment_vars written before the encrypted
    # column type existed — a database dump must not carry operator secrets.
    reencrypted = await encrypt_legacy_env_vars()
    if reencrypted:
        logger.info("Re-encrypted %d legacy plaintext environment_vars values", reencrypted)

    # Missed-schedule detection: the cursor persisted before shutdown makes
    # this first sweep cover the whole downtime window.
    try:
        from app.services.missed_runs import detect_missed_runs

        missed = await detect_missed_runs()
        if missed:
            logger.warning("Startup sweep recorded %d missed schedule(s)", missed)
    except Exception:
        logger.exception("Missed-run detection failed at startup; the periodic job will retry")

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


async def encrypt_legacy_env_vars() -> int:
    """Re-encrypt plaintext `environment_vars` rows written before the
    encrypted column type existed.

    The column type encrypts every new write, but old rows stay plaintext
    until something touches them, and until then every backup carries the
    operator's secrets in the clear. Assigning the same value back does not
    dirty the attribute, so each row is explicitly flag_modified — that
    routes it through the bind processor on flush and stores the ciphertext.

    Returns the number of rows rewritten.
    """
    from sqlalchemy import select
    from sqlalchemy.orm.attributes import flag_modified

    from app.database import async_session_maker
    from app.models.script import Script
    from app.models.script_version import ScriptVersion
    from app.secret_cipher import ENCRYPTED_PREFIX

    updated = 0
    async with async_session_maker() as db:
        # notlike() matches against the raw stored column, which is exactly
        # what we want: legacy plaintext, never the marker-prefixed form.
        scripts = (
            (
                await db.execute(
                    select(Script).where(
                        Script.environment_vars != "",
                        Script.environment_vars.notlike(ENCRYPTED_PREFIX + "%"),
                    )
                )
            )
            .scalars()
            .all()
        )
        for script in scripts:
            flag_modified(script, "environment_vars")
            updated += 1

        versions = (
            (
                await db.execute(
                    select(ScriptVersion).where(
                        ScriptVersion.environment_vars != "",
                        ScriptVersion.environment_vars.notlike(ENCRYPTED_PREFIX + "%"),
                    )
                )
            )
            .scalars()
            .all()
        )
        for version in versions:
            flag_modified(version, "environment_vars")
            updated += 1

        if updated:
            await db.commit()

    return updated


async def wait_for_database(attempts: int = 10, delay: float = 2.0) -> None:
    """Best-effort wait until the database answers ``SELECT 1``.

    Retries with a fixed delay and gives up after ``attempts`` — the app still
    starts (``/health`` will report the database as unhealthy) rather than
    crash-looping, but this absorbs the transient DNS/network race on cold
    container starts.
    """
    import asyncio

    from sqlalchemy import text

    from app.database import async_session_maker

    for attempt in range(1, attempts + 1):
        try:
            async with async_session_maker() as db:
                await db.execute(text("SELECT 1"))
            return
        except Exception as e:
            if attempt == attempts:
                logger.warning(
                    "Database not reachable after %d attempts (%s) — continuing; "
                    "/health will report it",
                    attempts,
                    e,
                )
                return
            logger.warning(
                "Database not reachable yet (attempt %d/%d): %s — retrying in %.1fs",
                attempt,
                attempts,
                e,
                delay,
            )
            await asyncio.sleep(delay)


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
app.add_middleware(CsrfOriginGuardMiddleware)
# Text-heavy pages (script editor's ~170KB HTML) and static assets
# (CodeMirror ~170KB, Tailwind output.css ~105KB) were transferred
# uncompressed — a real, noticeable slowdown for anyone not on the same
# LAN as the server. 500 bytes is comfortably below any page/asset here.
app.add_middleware(GZipMiddleware, minimum_size=500)


@app.middleware("http")
async def access_log(request: Request, call_next):
    """One log line per request: method, path, status, duration, user.

    Uvicorn's access log shows only the method and path; who did it and
    what it cost were invisible, which is what an audit trail needs. The
    user comes from the Authorization header when present — no DB lookup,
    so the header's own information is the log's.
    """
    start = time.perf_counter()
    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception:
        logger.exception("5xx while handling %s %s", request.method, request.url.path)
        raise
    finally:
        duration_ms = (time.perf_counter() - start) * 1000

    user = "-"
    auth = request.headers.get("authorization", "")
    if auth.startswith("Basic "):
        import base64

        try:
            user = (
                base64.b64decode(auth.split(" ", 1)[1])
                .decode("utf-8", errors="replace")
                .split(":", 1)[0]
            )
        except Exception:
            user = "-"

    logger.info(
        "request %s %s -> %s %.0fms user=%s",
        request.method,
        request.url.path,
        status_code,
        duration_ms,
        user,
    )
    return response


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
        metrics_registry.gauge_set("cronator_scripts_total", float(script_total))
        metrics_registry.gauge_set("cronator_executions_running", float(running))
        metrics_registry.gauge_set("cronator_artifacts_total", float(artifacts_total))
    except Exception:
        # Don't fail metrics scrape because of a DB hiccup
        pass

    # Scheduler jobs (in-process, always reachable)
    try:
        from app.services.scheduler import scheduler_service

        job_count = len(scheduler_service.scheduler.get_jobs())
        metrics_registry.gauge_set("cronator_scheduler_jobs", float(job_count))
    except Exception:
        pass

    metrics_registry.gauge_set("cronator_uptime_seconds", get_uptime_seconds())
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
    """Handle validation errors with detailed information.

    exc.errors() isn't JSON-serializable as-is: a custom field_validator
    that raises ValueError produces an error dict with
    ctx={"error": ValueError(...)} — the exception object itself. Passing
    that straight to JSONResponse crashes the handler with a TypeError,
    turning a 422 into an unhandled 500. jsonable_encoder converts it
    (and any other non-primitive pydantic puts in there) to a plain string.
    """
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": "Validation error",
            "errors": jsonable_encoder(exc.errors()),
            "body": jsonable_encoder(exc.body),
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


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Default JSON behavior everywhere, except a 403/404 on an HTML page route.

    require_admin (app/api/dependencies.py) raises a plain 403 the same
    way for /api/* calls and for the HTML page-action routes in
    pages.py (/scripts/{id}/toggle, /scripts/{id}/run, etc.) — without
    this, a viewer clicking a button the UI didn't hide would land on a
    raw {"detail": "Admin privileges required"} JSON blob in their
    browser instead of a page they can navigate away from. 401 keeps the
    default handling unconditionally: it carries the WWW-Authenticate
    header the browser needs to show its native Basic Auth prompt, which
    an HTML error page would silently break. The same HTML treatment for
    404: a mistyped URL, a deleted script or a deleted execution would
    otherwise dead-end the user on a bare {"detail": ...} JSON blob with
    no link back to the dashboard.
    """
    html_page_route = not request.url.path.startswith("/api/")
    if exc.status_code == status.HTTP_403_FORBIDDEN and html_page_route:
        return request.app.state.templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "page_title": "Access Denied",
                "status_code": exc.status_code,
                "message": exc.detail,
            },
            status_code=exc.status_code,
        )
    if exc.status_code == status.HTTP_404_NOT_FOUND and html_page_route:
        return request.app.state.templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "page_title": "Not Found",
                "status_code": exc.status_code,
                "message": exc.detail or "This page has moved, was deleted, or never existed.",
            },
            status_code=exc.status_code,
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=exc.headers,
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


def dt_filter(value, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Render a stored UTC timestamp in the operator's display timezone.

    Every page used to call .strftime() directly, and most did not even
    say "UTC" — an operator outside UTC read local-looking times that were
    quietly wrong. The stored value stays UTC; only the rendering moves.
    """
    from app.services.display_time import DEFAULT_DISPLAY_TIMEZONE, format_in_display_tz
    from app.services.settings_service import settings_service

    tz_name = settings_service.get_cached("display_timezone", DEFAULT_DISPLAY_TIMEZONE)
    return format_in_display_tz(value, tz_name, fmt)


app.state.templates.env.filters["dt"] = dt_filter


def t_global(text: str, **kwargs) -> str:
    """Translate a UI literal into the active locale (see app/services/i18n.py)."""
    from app.services.i18n import current_locale, translate

    return translate(text, current_locale(), **kwargs)


app.state.templates.env.globals["t"] = t_global


def lang_global() -> str:
    """The active locale, for <html lang> so screen readers pick the voice."""
    from app.services.i18n import current_locale

    return current_locale()


app.state.templates.env.globals["lang"] = lang_global


class CachedStaticFiles(StaticFiles):
    """StaticFiles never sends Cache-Control — every page navigation
    re-fetched the same ~170KB CodeMirror bundle and ~105KB CSS from
    scratch. These paths aren't content-hashed, so a max-age would serve
    stale assets for its whole duration after a deploy — caught this
    live: an app.js fix made during this same change would have stayed
    invisible for 24h to anyone who'd already loaded the page once.
    `no-cache` still saves the transfer (browser revalidates via the
    ETag StaticFiles already sets, gets a tiny 304 if unchanged) without
    ever risking stale content."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers.setdefault("Cache-Control", "no-cache")
        return response


# Setup static files (if needed)
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", CachedStaticFiles(directory=str(static_dir)), name="static")

# Include routers
app.include_router(api_router)

# The login flow — /login and /logout are the only anonymous routes in
# the app, mounted here rather than inside api_router so their
# exemption (and nothing else) is visible in one place.
app.include_router(auth_router)


async def get_migration_status() -> dict:
    """Best-effort Alembic drift snapshot: current revision vs head.

    Reads the current revision over the app's *async* engine, so it works
    with asyncpg — the previous implementation derived a sync URL and called
    ``create_engine()``, which required a sync driver (psycopg2) that isn't
    installed in the runtime image, so it always reported ``unavailable``.
    ``run_sync`` gives Alembic a sync-style Connection while staying on the
    already-installed async driver.
    """
    import os

    if os.getenv("SKIP_ALEMBIC_MIGRATIONS"):
        return {"status": "skipped", "reason": "SKIP_ALEMBIC_MIGRATIONS=1"}

    try:
        from alembic.config import Config
        from alembic.runtime.migration import MigrationContext
        from alembic.script import ScriptDirectory

        from app.database import async_session_maker

        script_dir = ScriptDirectory.from_config(Config("alembic.ini"))
        head_rev = script_dir.get_current_head()

        def _current_revision(sync_conn) -> str | None:
            return MigrationContext.configure(sync_conn).get_current_revision()

        async with async_session_maker() as db:
            conn = await db.connection()
            current_rev = await conn.run_sync(_current_revision)

        pending = current_rev != head_rev
        return {
            "status": "ok" if not pending else "pending",
            "current": current_rev,
            "head": head_rev,
            "pending": pending,
        }
    except Exception as e:
        return {"status": "error", "error": f"{type(e).__name__}: {e}"}


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
    checks["components"]["migrations"] = await get_migration_status()
    if checks["components"]["migrations"].get("pending"):
        checks["status"] = "degraded"

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
