"""
SSE streaming тесты против PostgreSQL.

Переиспользует TestStreamingSSE из integration-тестов.
Фикстура test_engine переопределена в tests/pg/conftest.py — все зависимые
фикстуры (db_session, test_client, execution_factory, …) автоматически
работают с PostgreSQL.
"""

from tests.integration.test_streaming import TestStreamingSSE

__all__ = ["TestStreamingSSE"]
