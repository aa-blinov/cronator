"""TDD tests for F7: PostgreSQL tests run in CI.

The README mentions tests/pg/ (testcontainers-based PostgreSQL suite) but the
existing CI (tests.yml, now ci.yml) only runs the SQLite suite. We add a
CI job that spins up PostgreSQL testcontainers and runs the pg/ suite.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_pg_tests_directory_exists():
    """The pg/ suite of tests must be present."""
    p = REPO_ROOT / "tests" / "pg"
    assert p.exists(), f"tests/pg directory missing at {p}"
    assert any(p.glob("test_*.py")), f"no test_*.py files in {p}"


def test_ci_workflow_has_postgres_job():
    """The CI workflow must include a job that runs the pg/ tests against PostgreSQL."""
    p = REPO_ROOT / ".github" / "workflows" / "ci.yml"
    content = p.read_text()
    assert "tests/pg" in content or "test-pg" in content or "postgres" in content.lower(), (
        f"CI workflow does not reference tests/pg or postgres:\n{content}"
    )


def test_ci_workflow_has_pg_service():
    """The pg job must spin up a PostgreSQL service container."""
    p = REPO_ROOT / ".github" / "workflows" / "ci.yml"
    content = p.read_text()
    # Postgres service container (services block + image)
    assert "postgres" in content.lower(), f"no postgres reference in CI:\n{content[:1000]}"
    # The pg job needs a postgres service to be reachable as 'db' or similar
    assert "services" in content or "image: postgres" in content, (
        f"no service block in CI:\n{content[:1000]}"
    )
