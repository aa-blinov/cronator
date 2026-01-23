"""Main FastAPI application entry point."""

import logging
import logging.handlers
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api import api_router
from app.config import get_settings
from app.database import close_db, init_db
from app.services.git_sync import git_sync_service
from app.services.scheduler import scheduler_service

settings = get_settings()

# Configure logging
log_dir = settings.data_dir / "logs"
log_dir.mkdir(parents=True, exist_ok=True)
log_file = log_dir / "cronator.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
        )
    ]
)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle manager."""
    logger.info("Starting Cronator...")
    
    # Ensure directories exist
    settings.ensure_directories()
    
    # Initialize database
    await init_db()
    logger.info("Database initialized")
    
    # Start scheduler
    await scheduler_service.start()
    logger.info("Scheduler started")
    
    # Cleanup stale executions
    from app.services.executor import executor_service
    await executor_service.cleanup_stale_executions()
    logger.info("Stale executions cleaned up")
    
    # Start git sync if enabled
    if settings.git_enabled:
        await git_sync_service.start()
        logger.info("Git sync started")
    
    logger.info(f"Cronator is running on http://{settings.host}:{settings.port}")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Cronator...")
    
    await scheduler_service.stop()
    await git_sync_service.stop()
    await close_db()
    
    logger.info("Cronator stopped")


# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    description="Python Script Scheduler with Web UI",
    version="0.1.0",
    lifespan=lifespan,
)

# Setup templates
templates_dir = Path(__file__).parent / "templates"
app.state.templates = Jinja2Templates(directory=str(templates_dir))

# Setup static files (if needed)
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Include routers
app.include_router(api_router)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "app": settings.app_name,
        "version": "0.1.0",
    }


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
