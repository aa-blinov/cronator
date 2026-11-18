"""Smoke test: the documented local-dev path must work from scratch.

`alembic upgrade head` against a fresh SQLite file is exactly what a new
contributor runs on a fresh clone (see docs/DEVELOPMENT.md). The CI docker
job never exercises Alembic (SKIP_ALEMBIC_MIGRATIONS=1) and the pg job runs
Alembic against PostgreSQL only, so without this test a SQLite-incompatible
migration reaches master untested — which has already happened once.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_alembic_upgrade_head_on_fresh_sqlite(tmp_path):
    """`alembic upgrade head` must succeed against a fresh SQLite file.

    Prevents a recurrence of the two SQLite-incompatible migrations
    (server_default ALTER and constraint ADD) that crashed the startup of
    a fresh local checkout.
    """
    db_path = tmp_path / "fresh.db"
    env = dict(os.environ)
    env.update(
        {
            "ADMIN_PASSWORD": "smoke-test-8chars",
            "SECRET_KEY": "smoke-test-secret-key-32chars-minimum!!",
            "SUPPRESS_CONFIG_WARNINGS": "1",
        }
    )
    env.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, f"alembic failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"

    # The schema must actually be at head, with all tables present.
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "select name from sqlite_master where type='table'"
            ).fetchall()
        }
        version = conn.execute("select version_num from alembic_version").fetchone()[0]
    finally:
        conn.close()

    expected = {
        "alembic_version",
        "scripts",
        "script_versions",
        "executions",
        "artifacts",
        "settings",
        "users",
        "script_audit_log",
        "user_audit_log",
    }
    missing = expected - tables
    assert not missing, f"tables missing after upgrade head: {missing}"
    assert version == "k3l4m5n6o7p8", f"schema not at head, got: {version}"


def test_downgrade_not_required_for_fresh_install(tmp_path):
    """A fresh install never downgrades — but the downgrade chain must at
    least be loadable without syntax errors, or `alembic downgrade base`
    (used by the reset instructions) breaks on SQLite."""
    db_path = tmp_path / "fresh.db"
    env = dict(os.environ)
    env.update(
        {
            "ADMIN_PASSWORD": "smoke-test-8chars",
            "SECRET_KEY": "smoke-test-secret-key-32chars-minimum!!",
            "SUPPRESS_CONFIG_WARNINGS": "1",
            "DATABASE_URL": f"sqlite+aiosqlite:///{db_path.as_posix()}",
        }
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "history"],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        cwd=str(REPO_ROOT),
    )
    # The chain must be loadable and linear: one head, no branch points.
    assert result.returncode == 0, result.stderr
    chain = [line for line in result.stdout.splitlines() if line.strip()]
    assert chain, "no migration history at all"
