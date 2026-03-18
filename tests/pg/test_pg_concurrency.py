"""
Concurrency интеграционные тесты против PostgreSQL.

Переиспользует TestConcurrencyIntegration из integration-тестов.
Фикстура test_engine переопределена в tests/pg/conftest.py —
все зависимые фикстуры работают с PostgreSQL через testcontainers.
"""

from tests.integration.test_concurrency import TestConcurrencyIntegration

__all__ = ["TestConcurrencyIntegration"]
