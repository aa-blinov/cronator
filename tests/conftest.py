"""Root pytest configuration shared by both tests/stateless and
tests/stateful — env vars and the event loop, nothing that touches a
database. DB-backed fixtures (test_engine, db_session, test_client,
script_factory, execution_factory, ...) live in tests/stateful/conftest.py
so a stateless test can never accidentally depend on one.
"""

import asyncio
import os

os.environ.setdefault("SUPPRESS_CONFIG_WARNINGS", "1")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password-ok")
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-chars-long-x")

import pytest


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
