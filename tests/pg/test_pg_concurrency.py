"""
Concurrency integration tests against PostgreSQL.

Reuses TestConcurrencyIntegration from the integration test suite.
The test_engine fixture is overridden in tests/pg/conftest.py —
all dependent fixtures run against PostgreSQL via testcontainers.
"""

from tests.integration.test_concurrency import TestConcurrencyIntegration

__all__ = ["TestConcurrencyIntegration"]
