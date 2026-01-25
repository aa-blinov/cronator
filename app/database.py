"""Database connection and session management."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


settings = get_settings()

# Create engine with connection pooling
# For SQLite, pooling options are ignored but don't cause errors
engine_kwargs = {
    "echo": settings.debug,
    "future": True,
}

# Add pooling settings for production databases (PostgreSQL, MySQL)
if not settings.database_url.startswith("sqlite"):
    engine_kwargs.update(
        {
            "pool_size": settings.db_pool_size,
            "max_overflow": settings.db_max_overflow,
            "pool_timeout": settings.db_pool_timeout,
            "pool_recycle": settings.db_pool_recycle,
            "pool_pre_ping": settings.db_pool_pre_ping,
        }
    )

engine = create_async_engine(
    settings.database_url,
    **engine_kwargs,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for getting database sessions."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Initialize database tables (used in tests only).

    In production, use Alembic migrations instead (alembic upgrade head).
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Close database connection."""
    await engine.dispose()


# Import all models to register them with Base.metadata
# This ensures tables are created when using Base.metadata.create_all()
from app.models import Execution, Script, ScriptVersion, Setting  # noqa: F401, E402
