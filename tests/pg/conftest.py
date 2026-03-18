"""
PostgreSQL fixtures for tests/pg/.

Переопределяет фикстуру test_engine из корневого conftest.py:
все тесты в этой директории автоматически работают с PostgreSQL
(через testcontainers) вместо SQLite.

Запуск:
    pytest tests/pg/              # требует Docker
    USE_TESTCONTAINERS=0 pytest tests/pg/  # пропустить если Docker недоступен
"""

import os

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine

from app.database import Base


# ─────────────────────────── PostgreSQL container ────────────────────────────


@pytest.fixture(scope="session")
def _pg_container():
    """
    Запускает PostgreSQL 16 контейнер один раз на всю сессию.
    Пропускает если testcontainers не установлен или Docker недоступен.
    """
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
        yield container
        container.stop()
    except Exception as exc:
        pytest.skip(f"Docker недоступен для testcontainers: {exc}")


@pytest.fixture(scope="session")
def _pg_url(_pg_container) -> str:
    """Asyncpg URL для тестового PostgreSQL."""
    raw_url: str = _pg_container.get_connection_url()
    # testcontainers возвращает psycopg2 URL → заменяем на asyncpg
    return raw_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://").replace(
        "postgresql://", "postgresql+asyncpg://"
    )


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
