"""Smoke tests that nothing in the documented dev flow broke."""

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


def test_downgrade_base_and_reupgrade_roundtrip(tmp_path):
    """`alembic downgrade base` + `upgrade head` must survive on SQLite.

    The reset instructions (README) put the downgrade right next to the
    upgrade; a SQLite-incompatible downgrade has historically been invisible
    to the CI suites (docker skips Alembic, pg runs it on PostgreSQL).
    """
    db_path = tmp_path / "roundtrip.db"
    env = dict(os.environ)
    env.update(
        {
            "ADMIN_PASSWORD": "smoke-test-8chars",
            "SECRET_KEY": "smoke-test-secret-key-32chars-minimum!!",
            "SUPPRESS_CONFIG_WARNINGS": "1",
            "DATABASE_URL": f"sqlite+aiosqlite:///{db_path.as_posix()}",
        }
    )

    up = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=str(REPO_ROOT),
    )
    assert up.returncode == 0, up.stderr[-400:]

    down = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "base"],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=str(REPO_ROOT),
    )
    assert down.returncode == 0, down.stderr[-400:]

    again = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=str(REPO_ROOT),
    )
    assert again.returncode == 0, again.stderr[-400:]
