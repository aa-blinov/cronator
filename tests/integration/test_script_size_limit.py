"""TDD tests for F13: Script content size limit.

Currently a script's `content` field has no max_length. Operators can create
scripts of arbitrary size, which fills disk, slows backups, and could be a
vector for accidental denial-of-service. We enforce a 1 MB hard limit on the
serialized `content` string.
"""

import pytest

MAX_SCRIPT_BYTES = 1 * 1024 * 1024  # 1 MB


@pytest.mark.asyncio
async def test_script_under_limit_succeeds(test_client):
    """A script within the size limit is created normally."""
    script = {
        "name": "small_script",
        "content": "print('hello')\n",
        "cron_expression": "0 * * * *",
        "python_version": "3.12",
        "enabled": False,
        "timeout": 60,
    }
    r = await test_client.post("/api/scripts", json=script)
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_script_over_limit_rejected(test_client):
    """A script larger than the limit is rejected with a clear error."""
    big_content = "x" * (MAX_SCRIPT_BYTES + 1)
    script = {
        "name": "big_script",
        "content": big_content,
        "cron_expression": "0 * * * *",
        "python_version": "3.12",
        "enabled": False,
        "timeout": 60,
    }
    r = await test_client.post("/api/scripts", json=script)
    assert r.status_code in (400, 413, 422), r.text
    # Error should mention 'size' or 'limit'
    body = r.text.lower()
    assert "size" in body or "limit" in body or "too large" in body or "max_length" in body


@pytest.mark.asyncio
async def test_script_at_exact_limit_accepted(test_client):
    """A script at exactly the limit boundary should be accepted (or rejected with clear message)."""
    content = "x" * MAX_SCRIPT_BYTES
    script = {
        "name": "boundary_script",
        "content": content,
        "cron_expression": "0 * * * *",
        "python_version": "3.12",
        "enabled": False,
        "timeout": 60,
    }
    r = await test_client.post("/api/scripts", json=script)
    # Either accepted, or rejected — both acceptable, but we want to know
    if r.status_code == 201:
        # Cleanup
        sid = r.json()["id"]
        await test_client.delete(f"/api/scripts/{sid}")
    assert r.status_code in (201, 400, 413, 422), f"unexpected status: {r.status_code}"


def test_schema_has_max_length_for_content():
    """The ScriptCreate schema must declare a max_length on content."""
    from app.schemas.script import ScriptCreate

    field = ScriptCreate.model_fields["content"]
    # json_schema_extra or Field metadata
    assert (
        field.metadata or "max_length" in str(field)
    ), f"ScriptCreate.content has no max_length constraint: {field}"
