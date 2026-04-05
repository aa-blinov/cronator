"""
PostgreSQL fixtures for tests/pg/.

Overrides the test_engine fixture from the root conftest.py:
all tests in this directory automatically run against PostgreSQL.

Operating modes:
  1. CI / docker-compose: TEST_DATABASE_URL already set to postgresql+asyncpg://...
     → used directly, no testcontainers needed.
  2. Local with Docker: testcontainers spins up postgres:16-alpine.
  3. Without Docker: tests are skipped.

Running:
    pytest tests/pg/                      # requires PostgreSQL (env var or Docker)
    USE_TESTCONTAINERS=0 pytest tests/pg/ # force-skip
"""

import os

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine

from app.database import Base


def _normalize_pg_url(url: str) -> str:
    """Normalize any postgres URL to postgresql+asyncpg://..."""
    url = url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


# ─────────────────────────── pg url ──────────────────────────────────────────


@pytest.fixture(scope="session")
def _pg_url() -> str:
    """
    Return the asyncpg URL for the test PostgreSQL instance.

    Priority:
      1. TEST_DATABASE_URL from env, if it points to PostgreSQL.
      2. Testcontainers (local Docker).
      3. pytest.skip.
    """
    if os.getenv("USE_TESTCONTAINERS") == "0":
        pytest.skip("USE_TESTCONTAINERS=0 — pg tests skipped")

    ext_url = os.getenv("TEST_DATABASE_URL", "")
    if "postgresql" in ext_url:
        return _normalize_pg_url(ext_url)

    # Fallback: testcontainers
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers not installed: pip install testcontainers[postgres]")

    try:
        container = PostgresContainer(
            "postgres:16-alpine",
            username="test_user",
            password="test_password",
            dbname="cronator_test",
        )
        container.start()
        # Store container reference for teardown
        _pg_url._container = container  # type: ignore[attr-defined]
        return _normalize_pg_url(container.get_connection_url())
    except Exception as exc:
        pytest.skip(f"Docker not available for testcontainers: {exc}")


@pytest.fixture(scope="session", autouse=False)
def _pg_container_cleanup(_pg_url):
    """Stop the testcontainers container after the session (if one was started)."""
    yield
    container = getattr(_pg_url, "_container", None)
    if container is not None:
        container.stop()


# ─────────────────────────── override test_engine ────────────────────────────


@pytest_asyncio.fixture(scope="function")
async def test_engine(_pg_url: str):
    """
    Override test_engine from the root conftest.py.
    Each test gets a clean schema (drop + create).
    """
    engine = create_async_engine(_pg_url, echo=False, future=True)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()
