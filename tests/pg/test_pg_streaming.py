"""
SSE streaming tests against PostgreSQL.

Reuses TestStreamingSSE from the integration test suite.
The test_engine fixture is overridden in tests/pg/conftest.py — all dependent
fixtures (db_session, test_client, execution_factory, …) automatically
run against PostgreSQL.
"""

from tests.integration.test_streaming import TestStreamingSSE

__all__ = ["TestStreamingSSE"]
