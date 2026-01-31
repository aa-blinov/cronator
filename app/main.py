"""Main FastAPI application entry point."""

import logging
import logging.handlers
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from app.api import api_router
from app.config import get_settings
from app.database import close_db
from app.services.scheduler import scheduler_service

settings = get_settings()

# Configure logging
log_dir = settings.logs_dir
log_file = log_dir / "cronator.log"

# Create handlers list - always include StreamHandler
handlers = [logging.StreamHandler()]

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
    handlers.append(file_handler)
except (PermissionError, OSError) as e:
    # If we can't write to the log file, just use StreamHandler
    # This allows the app to start even if log directory has permission issues
    import sys

    print(f"Warning: Could not create log file at {log_file}: {e}", file=sys.stderr)
    print("Warning: Logging to file disabled. Using console logging only.", file=sys.stderr)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=handlers,
)
logger = logging.getLogger(__name__)

settings = get_settings()


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

    # Start scheduler
    await scheduler_service.start()
    logger.info("Scheduler started")

    # Cleanup stale executions
    from app.services.executor import executor_service

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

    # Shutdown
    logger.info("Shutting down Cronator...")

    await scheduler_service.stop()
    await close_db()

    logger.info("Cronator stopped")


# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    description="Python Script Scheduler with Web UI",
    version="0.1.0",
    lifespan=lifespan,
)


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
    """Enhanced health check endpoint with detailed status."""
    from app.database import async_session_maker

    checks = {
        "status": "healthy",
        "app": settings.app_name,
        "version": "0.1.0",
        "timestamp": datetime.now(UTC).isoformat(),
        "components": {
            "database": "unknown",
            "scheduler": "unknown",
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

    # Scheduler check
    try:
        is_running = scheduler_service.scheduler.running
        checks["components"]["scheduler"] = "running" if is_running else "stopped"
        if not is_running:
            checks["status"] = "degraded"
    except Exception as e:
        checks["components"]["scheduler"] = f"error: {type(e).__name__}"
        checks["status"] = "degraded"
        logger.error(f"Scheduler health check failed: {e}")

    # Return 503 if unhealthy
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
