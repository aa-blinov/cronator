"""environment_vars is encrypted at rest (EncryptedText column type).

The API, the executor and version snapshots work in plaintext; the cipher
exists only between the ORM and the database. These tests pin that contract
from the outside: what the API accepts and returns, what the raw column
holds, and what the audit trail records.
"""

from sqlalchemy import text

from app.secret_cipher import ENCRYPTED_PREFIX

PLAIN_ENV = '{"DB_PASSWORD": "hunter2", "API_TOKEN": "tok-123"}'


async def _raw_env_vars(db_session, table: str, row_id: int) -> str:
    """Read the column the way a database dump would: no ORM, no decrypt."""
    result = await db_session.execute(
        text(f"SELECT environment_vars FROM {table} WHERE id = :row_id"),  # noqa: S608
        {"row_id": row_id},
    )
    return result.scalar_one()


async def test_created_script_env_vars_are_encrypted_at_rest(test_client, db_session):
    resp = await test_client.post(
        "/api/scripts",
        json={"name": "env-enc-create", "content": "print('ok')", "environment_vars": PLAIN_ENV},
    )
    assert resp.status_code == 201, resp.text
    script_id = resp.json()["id"]

    raw = await _raw_env_vars(db_session, "scripts", script_id)
    assert raw.startswith(ENCRYPTED_PREFIX), raw
    assert "hunter2" not in raw
    assert "tok-123" not in raw


async def test_api_returns_env_vars_as_plaintext(test_client):
    resp = await test_client.post(
        "/api/scripts",
        json={"name": "env-enc-read", "content": "print('ok')", "environment_vars": PLAIN_ENV},
    )
    assert resp.status_code == 201, resp.text
    script_id = resp.json()["id"]

    read = await test_client.get(f"/api/scripts/{script_id}")
    assert read.status_code == 200, read.text
    assert read.json()["environment_vars"] == PLAIN_ENV


async def test_updated_env_vars_stay_encrypted_at_rest(test_client, db_session):
    resp = await test_client.post(
        "/api/scripts",
        json={"name": "env-enc-update", "content": "print('ok')", "environment_vars": ""},
    )
    assert resp.status_code == 201, resp.text
    script_id = resp.json()["id"]

    updated = await test_client.put(
        f"/api/scripts/{script_id}",
        json={"environment_vars": PLAIN_ENV},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["environment_vars"] == PLAIN_ENV

    raw = await _raw_env_vars(db_session, "scripts", script_id)
    assert raw.startswith(ENCRYPTED_PREFIX)
    assert "hunter2" not in raw


async def test_version_snapshots_are_encrypted_at_rest(test_client, db_session):
    resp = await test_client.post(
        "/api/scripts",
        json={
            "name": "env-enc-version",
            "content": "print('v1')",
            "environment_vars": PLAIN_ENV,
            "dependencies": "requests>=2.31",
        },
    )
    assert resp.status_code == 201, resp.text
    script_id = resp.json()["id"]

    # A content change creates a new version snapshot carrying the env vars.
    changed = await test_client.put(f"/api/scripts/{script_id}", json={"content": "print('v2')"})
    assert changed.status_code == 200, changed.text

    versions = await test_client.get(f"/api/scripts/{script_id}/versions")
    assert versions.status_code == 200, versions.text
    version_rows = versions.json()["items"]
    assert version_rows, "expected at least one version snapshot"

    raw = await _raw_env_vars(db_session, "script_versions", version_rows[0]["id"])
    assert raw.startswith(ENCRYPTED_PREFIX)
    assert "hunter2" not in raw


async def test_revert_returns_plaintext_env_vars(test_client):
    resp = await test_client.post(
        "/api/scripts",
        json={"name": "env-enc-revert", "content": "print('v1')", "environment_vars": PLAIN_ENV},
    )
    assert resp.status_code == 201, resp.text
    script_id = resp.json()["id"]

    # Change env vars so the revert has something to come back to.
    changed = await test_client.put(
        f"/api/scripts/{script_id}", json={"environment_vars": '{"OTHER": "1"}'}
    )
    assert changed.status_code == 200, changed.text

    reverted = await test_client.post(f"/api/scripts/{script_id}/revert/1")
    assert reverted.status_code == 200, reverted.text

    read = await test_client.get(f"/api/scripts/{script_id}")
    assert read.json()["environment_vars"] == PLAIN_ENV


async def test_audit_log_redacts_env_vars(test_client):
    resp = await test_client.post(
        "/api/scripts",
        json={"name": "env-enc-audit", "content": "print('ok')", "environment_vars": ""},
    )
    assert resp.status_code == 201, resp.text
    script_id = resp.json()["id"]

    updated = await test_client.put(
        f"/api/scripts/{script_id}", json={"environment_vars": PLAIN_ENV}
    )
    assert updated.status_code == 200, updated.text

    audit = await test_client.get(f"/api/scripts/{script_id}/audit")
    assert audit.status_code == 200, audit.text
    env_entries = [e for e in audit.json()["items"] if e["field_name"] == "environment_vars"]
    assert env_entries, f"no audit entry for environment_vars; items: {audit.json()['items']}"

    for entry in env_entries:
        assert entry["old_value"] == "<redacted>", entry
        assert entry["new_value"] == "<redacted>", entry


async def test_startup_sweep_reencrypts_legacy_plaintext(test_client, db_session):
    """Rows written before the encrypted type existed get rewritten on boot."""
    from app.main import encrypt_legacy_env_vars

    resp = await test_client.post(
        "/api/scripts",
        json={"name": "env-enc-sweep", "content": "print('ok')", "environment_vars": ""},
    )
    assert resp.status_code == 201, resp.text
    script_id = resp.json()["id"]

    # Plant a legacy plaintext row the way an old deployment would hold it:
    # a raw SQL write, bypassing the ORM's bind processor entirely.
    await db_session.execute(
        text("UPDATE scripts SET environment_vars = 'PLAIN=legacy-secret' WHERE id = :sid"),
        {"sid": script_id},
    )
    await db_session.commit()

    rewritten = await encrypt_legacy_env_vars()
    assert rewritten >= 1, "the sweep must rewrite the planted plaintext row"

    raw = await _raw_env_vars(db_session, "scripts", script_id)
    assert raw.startswith(ENCRYPTED_PREFIX), raw
    assert "legacy-secret" not in raw

    # And the ORM still reads it back as the plaintext the operator entered.
    # The row may already sit in this session's identity map from the API
    # call, so expire first to force a fresh load through the column type.
    db_session.expire_all()
    from app.models.script import Script

    script = await db_session.get(Script, script_id)
    assert script.environment_vars == "PLAIN=legacy-secret"

    # A second sweep finds nothing left to do.
    assert await encrypt_legacy_env_vars() == 0
