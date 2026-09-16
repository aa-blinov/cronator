"""TDD tests for F11: Audit log for script changes.

Currently we track ScriptVersion (content snapshots) but don't track WHO made
WHAT change to a script. Operators want to know: "when did the timeout change
from 3600 to 7200, and who changed it?" — not just that version 17 exists.

We add a ScriptAuditLog table that records:
- script_id
- field_name (e.g. "timeout", "enabled", "cron_expression")
- old_value, new_value
- changed_by (user identifier)
- changed_at (timestamp)

The audit log is queried via /api/scripts/{id}/audit.
"""

import pytest


@pytest.mark.asyncio
async def test_script_update_creates_audit_entries(test_client):
    """Updating a script records an audit entry for each changed field."""
    # Create a script
    create = await test_client.post(
        "/api/scripts",
        json={
            "name": "audit_test_script",
            "content": "print('v1')\n",
            "cron_expression": "0 * * * *",
            "python_version": "3.12",
            "enabled": False,
            "timeout": 60,
        },
    )
    assert create.status_code == 201, create.text
    script_id = create.json()["id"]

    # Update a couple of fields
    update = await test_client.put(
        f"/api/scripts/{script_id}",
        json={"timeout": 120, "cron_expression": "*/5 * * * *"},
    )
    assert update.status_code == 200, update.text

    # Audit log must show entries for the changed fields
    audit = await test_client.get(f"/api/scripts/{script_id}/audit")
    assert audit.status_code == 200, audit.text
    entries = audit.json()["items"]
    changed_fields = {e["field_name"] for e in entries}
    assert "timeout" in changed_fields, f"no audit for timeout; entries: {entries}"
    assert "cron_expression" in changed_fields, f"no audit for cron_expression; entries: {entries}"


@pytest.mark.asyncio
async def test_audit_entry_has_old_and_new_value(test_client):
    """Each audit entry records the old and new values for the change."""
    create = await test_client.post(
        "/api/scripts",
        json={
            "name": "audit_values",
            "content": "print('x')",
            "cron_expression": "0 * * * *",
            "python_version": "3.12",
            "enabled": False,
            "timeout": 60,
        },
    )
    script_id = create.json()["id"]

    await test_client.put(
        f"/api/scripts/{script_id}",
        json={"timeout": 600},
    )

    audit = await test_client.get(f"/api/scripts/{script_id}/audit")
    entries = audit.json()["items"]
    timeout_entry = next((e for e in entries if e["field_name"] == "timeout"), None)
    assert timeout_entry is not None, f"no timeout audit entry; entries: {entries}"
    # old/new may be strings
    assert timeout_entry["old_value"] == "60", timeout_entry
    assert timeout_entry["new_value"] == "600", timeout_entry


@pytest.mark.asyncio
async def test_audit_records_changed_by(test_client):
    """Each audit entry records who made the change."""
    create = await test_client.post(
        "/api/scripts",
        json={
            "name": "audit_who",
            "content": "print('x')",
            "cron_expression": "0 * * * *",
            "python_version": "3.12",
            "enabled": False,
            "timeout": 60,
        },
    )
    script_id = create.json()["id"]

    await test_client.put(f"/api/scripts/{script_id}", json={"timeout": 120})

    audit = await test_client.get(f"/api/scripts/{script_id}/audit")
    entries = audit.json()["items"]
    assert all("changed_by" in e for e in entries), entries
    assert all(e["changed_by"] for e in entries), entries


@pytest.mark.asyncio
async def test_audit_endpoint_returns_empty_for_new_script(test_client):
    """A freshly created script may have no audit entries yet."""
    # Actually: create itself doesn't audit (it's a baseline). Updates do.
    create = await test_client.post(
        "/api/scripts",
        json={
            "name": "audit_empty",
            "content": "print('x')",
            "cron_expression": "0 * * * *",
            "python_version": "3.12",
            "enabled": False,
            "timeout": 60,
        },
    )
    script_id = create.json()["id"]
    audit = await test_client.get(f"/api/scripts/{script_id}/audit")
    assert audit.status_code == 200
    # Either empty list or list of create entries — either is acceptable
    assert isinstance(audit.json()["items"], list)


@pytest.mark.asyncio
async def test_audit_endpoint_paginates(test_client):
    """Audit endpoint supports pagination."""
    create = await test_client.post(
        "/api/scripts",
        json={
            "name": "audit_paginate",
            "content": "print('x')",
            "cron_expression": "0 * * * *",
            "python_version": "3.12",
            "enabled": False,
            "timeout": 60,
        },
    )
    script_id = create.json()["id"]
    # Make several updates
    for i in range(3):
        await test_client.put(
            f"/api/scripts/{script_id}",
            json={"timeout": 60 + i},
        )
    audit = await test_client.get(f"/api/scripts/{script_id}/audit?page=1&per_page=2")
    assert audit.status_code == 200
    body = audit.json()
    assert "items" in body
    assert body["per_page"] == 2
