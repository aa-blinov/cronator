"""TDD tests for Q5: Duplicate script endpoint.

Q5 adds a `POST /api/scripts/{id}/duplicate` endpoint that creates a new
Script row copying all editable fields (name + "-copy", same content,
cron, env, deps, timeout, version) and a "Duplicate" button on the
script detail page that calls it.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_duplicate_creates_new_script(test_client, script_factory):
    """Duplicating a script returns 201 with a new id."""
    original = await script_factory(name="orig_q5", content="print(1)")

    r = await test_client.post(f"/api/scripts/{original.id}/duplicate")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"] != original.id
    assert "orig_q5" in body["name"]
    assert body["name"].endswith("-copy") or body["name"] == "orig_q5-copy"


@pytest.mark.asyncio
async def test_duplicate_copies_all_editable_fields(test_client, script_factory):
    """The duplicate has the same content/cron/env/deps/timeout as the original."""
    original = await script_factory(
        name="orig_fields_q5",
        content="print('copied content')",
        cron_expression="*/15 * * * *",
        enabled=False,
        python_version="3.11",
        timeout=1234,
        dependencies="requests==2.31.0",
        environment_vars="FOO=bar\nBAZ=qux",
        description="original desc",
    )

    r = await test_client.post(f"/api/scripts/{original.id}/duplicate")
    assert r.status_code == 201, r.text
    dup = r.json()

    assert dup["content"] == "print('copied content')"
    assert dup["cron_expression"] == "*/15 * * * *"
    assert dup["enabled"] is False  # always disabled to avoid surprise scheduler activity
    assert dup["python_version"] == "3.11"
    assert dup["timeout"] == 1234
    assert dup["dependencies"] == "requests==2.31.0"
    assert dup["environment_vars"] == "FOO=bar\nBAZ=qux"
    assert dup["description"] == "original desc"


@pytest.mark.asyncio
async def test_duplicate_is_disabled_by_default(test_client, script_factory):
    """The duplicate is always created disabled so it doesn't start running
    on the same schedule as the original."""
    original = await script_factory(name="orig_enabled_q5", content="print(1)", enabled=True)

    r = await test_client.post(f"/api/scripts/{original.id}/duplicate")
    assert r.status_code == 201, r.text
    assert r.json()["enabled"] is False


@pytest.mark.asyncio
async def test_duplicate_increments_copy_suffix(test_client, script_factory):
    """Re-duplicating the same original appends -copy-2, -copy-3, etc."""
    original = await script_factory(name="orig_incr_q5", content="print(1)")

    r1 = await test_client.post(f"/api/scripts/{original.id}/duplicate")
    r2 = await test_client.post(f"/api/scripts/{original.id}/duplicate")
    r3 = await test_client.post(f"/api/scripts/{original.id}/duplicate")

    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r3.status_code == 201
    names = [r1.json()["name"], r2.json()["name"], r3.json()["name"]]
    assert "orig_incr_q5-copy" in names
    assert "orig_incr_q5-copy-2" in names
    assert "orig_incr_q5-copy-3" in names


@pytest.mark.asyncio
async def test_duplicate_unknown_script_returns_404(test_client):
    """Duplicating a non-existent script returns 404."""
    r = await test_client.post("/api/scripts/99999999/duplicate")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_duplicate_appends_audit_field_change(test_client, script_factory):
    """Duplicating does NOT touch the original script — only adds a row."""
    from sqlalchemy import select

    from app.database import async_session_maker
    from app.models.script import Script

    original = await script_factory(name="orig_audit_q5", content="print(1)")
    r = await test_client.post(f"/api/scripts/{original.id}/duplicate")
    assert r.status_code == 201

    # Re-read the original from the DB and confirm content is unchanged
    async with async_session_maker() as db:
        result = await db.execute(select(Script).where(Script.id == original.id))
        fresh = result.scalar_one()
        assert fresh.content == "print(1)"
        assert fresh.name == "orig_audit_q5"