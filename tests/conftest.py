"""Pytest configuration and fixtures for Cronator tests."""

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.execution import Execution, ExecutionStatus
from app.models.script import Script


# Test database URL (in-memory SQLite)
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def test_engine():
    """Create test database engine."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        future=True,
    )
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield engine
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create test database session."""
    async_session = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    
    async with async_session() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture(scope="function")
async def test_client(test_engine, db_session) -> AsyncGenerator[AsyncClient, None]:
    """Create test HTTP client with test database and auth."""
    import base64
    from app.database import get_db
    from app.main import app
    from app.api.dependencies import verify_credentials

    # Override database dependency
    async def override_get_db():
        yield db_session

    # Override auth dependency - always return test user
    def override_verify_credentials():
        return "test_user"

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[verify_credentials] = override_verify_credentials

    transport = ASGITransport(app=app)
    
    # Add Basic Auth header for any endpoints that might check it directly
    auth = base64.b64encode(b"admin:admin").decode("ascii")
    headers = {"Authorization": f"Basic {auth}"}
    
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers=headers,
    ) as client:
        yield client
    
    # Clear overrides after test
    app.dependency_overrides.clear()


# --- Factory fixtures ---

@pytest_asyncio.fixture
async def script_factory(db_session: AsyncSession):
    """Factory for creating test scripts."""
    created_scripts: list[Script] = []

    async def _create_script(
        name: str = "test_script",
        description: str = "Test script description",
        path: str = "/scripts/test_script/main.py",
        content: str = "print('Hello, World!')",
        cron_expression: str = "0 * * * *",
        enabled: bool = True,
        python_version: str = "3.11",
        timeout: int = 3600,
        **kwargs: Any,
    ) -> Script:
        script = Script(
            name=name,
            description=description,
            path=path,
            content=content,
            cron_expression=cron_expression,
            enabled=enabled,
            python_version=python_version,
            timeout=timeout,
            **kwargs,
        )
        db_session.add(script)
        await db_session.commit()
        await db_session.refresh(script)
        created_scripts.append(script)
        return script

    yield _create_script


@pytest_asyncio.fixture
async def execution_factory(db_session: AsyncSession):
    """Factory for creating test executions."""

    async def _create_execution(
        script_id: int,
        status: str = ExecutionStatus.SUCCESS.value,
        exit_code: int | None = 0,
        stdout: str = "",
        stderr: str = "",
        triggered_by: str = "test",
        is_test: bool = True,
        **kwargs: Any,
    ) -> Execution:
        execution = Execution(
            script_id=script_id,
            status=status,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            triggered_by=triggered_by,
            is_test=is_test,
            **kwargs,
        )
        db_session.add(execution)
        await db_session.commit()
        await db_session.refresh(execution)
        return execution

    yield _create_execution


# --- Sample data fixtures ---

@pytest_asyncio.fixture
async def sample_script(script_factory) -> Script:
    """Create a sample script for testing."""
    return await script_factory(
        name="sample_script",
        content="print('Sample script output')",
    )


@pytest_asyncio.fixture
async def sample_execution(execution_factory, sample_script: Script) -> Execution:
    """Create a sample execution for testing."""
    return await execution_factory(
        script_id=sample_script.id,
        stdout="Sample script output\n",
        exit_code=0,
    )
