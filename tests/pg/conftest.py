"""
PostgreSQL fixtures for tests/pg/.

Переопределяет фикстуру test_engine из корневого conftest.py:
все тесты в этой директории автоматически работают с PostgreSQL.

Режимы работы:
  1. CI / docker-compose: TEST_DATABASE_URL уже postgresql+asyncpg://...
     → используется напрямую, testcontainers не нужен.
  2. Локально с Docker: testcontainers запускает postgres:16-alpine.
  3. Без Docker: тесты пропускаются.

Запуск:
    pytest tests/pg/              # требует PostgreSQL (env var или Docker)
    USE_TESTCONTAINERS=0 pytest tests/pg/  # принудительно пропустить
"""

import os

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine

from app.database import Base


def _normalize_pg_url(url: str) -> str:
    """Приводит любой postgres URL к postgresql+asyncpg://..."""
    url = url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


# ─────────────────────────── pg url ──────────────────────────────────────────


@pytest.fixture(scope="session")
def _pg_url() -> str:
    """
    Возвращает asyncpg URL для тестового PostgreSQL.

    Приоритет:
      1. TEST_DATABASE_URL из env, если уже указывает на PostgreSQL.
      2. Testcontainers (локальный Docker).
      3. pytest.skip.
    """
    if os.getenv("USE_TESTCONTAINERS") == "0":
        pytest.skip("USE_TESTCONTAINERS=0 — pg тесты пропущены")

    ext_url = os.getenv("TEST_DATABASE_URL", "")
    if "postgresql" in ext_url:
        return _normalize_pg_url(ext_url)

    # Fallback: testcontainers
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers не установлен: pip install testcontainers[postgres]")

    try:
        container = PostgresContainer(
            "postgres:16-alpine",
            username="test_user",
            password="test_password",
            dbname="cronator_test",
        )
        container.start()
        # Храним контейнер в атрибуте чтобы остановить в финализаторе
        _pg_url._container = container  # type: ignore[attr-defined]
        return _normalize_pg_url(container.get_connection_url())
    except Exception as exc:
        pytest.skip(f"Docker недоступен для testcontainers: {exc}")


@pytest.fixture(scope="session", autouse=False)
def _pg_container_cleanup(_pg_url):
    """Останавливает testcontainers-контейнер после сессии (если он был запущен)."""
    yield
    container = getattr(_pg_url, "_container", None)
    if container is not None:
        container.stop()


# ─────────────────────────── override test_engine ────────────────────────────


@pytest_asyncio.fixture(scope="function")
async def test_engine(_pg_url: str):
    """
    Переопределяет test_engine из корневого conftest.py.
    Каждый тест получает чистую схему (drop + create).
    """
    engine = create_async_engine(_pg_url, echo=False, future=True)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()
