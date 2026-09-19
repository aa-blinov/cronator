"""TDD tests for Q2: server-side search across scripts and executions.

Q2 — Server-side поиск по name / content / output. The current `?search=`
on /api/scripts only matches the script name; we extend it to also match
description, cron_expression, and content. /api/executions has no search
at all; we add one that matches script name + stdout + stderr.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_scripts_search_matches_name(test_client, script_factory):
    """The classic case: search by name finds the script."""
    await script_factory(name="alpha_unique", content="print(1)")
    await script_factory(name="beta_unique", content="print(2)")

    r = await test_client.get("/api/scripts", params={"search": "alpha_unique"})
    assert r.status_code == 200
    body = r.json()
    items = body.get("items", body) if isinstance(body, dict) else body
    names = [s.get("name") for s in items]
    assert "alpha_unique" in names
    assert "beta_unique" not in names


@pytest.mark.asyncio
async def test_scripts_search_matches_content(test_client, script_factory):
    """Search by a token that lives only in the script's content."""
    await script_factory(name="report_q2_a", content="print('apple_pie_marker')")
    await script_factory(name="report_q2_b", content="print('unrelated content')")

    r = await test_client.get("/api/scripts", params={"search": "apple_pie_marker"})
    assert r.status_code == 200
    body = r.json()
    items = body.get("items", body) if isinstance(body, dict) else body
    names = [s.get("name") for s in items]
    assert "report_q2_a" in names
    assert "report_q2_b" not in names


@pytest.mark.asyncio
async def test_scripts_search_matches_description(test_client, script_factory):
    """Search by a token that lives only in the description."""
    await script_factory(name="script_desc_a", description="zz_unique_token_zz", content="print(1)")
    await script_factory(name="script_desc_b", description="plain", content="print(2)")

    r = await test_client.get("/api/scripts", params={"search": "zz_unique_token_zz"})
    assert r.status_code == 200
    body = r.json()
    items = body.get("items", body) if isinstance(body, dict) else body
    names = [s.get("name") for s in items]
    assert "script_desc_a" in names
    assert "script_desc_b" not in names


@pytest.mark.asyncio
async def test_scripts_search_is_case_insensitive(test_client, script_factory):
    await script_factory(name="Mixed_Case_Script", content="print(1)")

    r = await test_client.get("/api/scripts", params={"search": "mixed_case_script"})
    assert r.status_code == 200
    items = r.json().get("items", r.json())
    names = [s.get("name") for s in items]
    assert "Mixed_Case_Script" in names


@pytest.mark.asyncio
async def test_executions_search_matches_stdout(test_client, script_factory, execution_factory):
    """Search by a marker that appears in stdout of one execution."""
    script = await script_factory(name="exec_search_q2", content="print(1)")
    await execution_factory(
        script_id=script.id, stdout="found_marker_token_here\n", status="success"
    )
    other_script = await script_factory(name="exec_search_q2_other", content="print(1)")
    await execution_factory(script_id=other_script.id, stdout="nothing relevant", status="success")

    r = await test_client.get("/api/executions", params={"search": "found_marker_token_here"})
    assert r.status_code == 200
    body = r.json()
    items = body.get("items", body) if isinstance(body, dict) else body
    assert len(items) == 1
    assert items[0]["script_id"] == script.id


@pytest.mark.asyncio
async def test_executions_search_matches_stderr(test_client, script_factory, execution_factory):
    """Search by a marker that appears in stderr of one execution."""
    script = await script_factory(name="exec_search_stderr", content="print(1)")
    await execution_factory(script_id=script.id, stderr="error_marker_token_q2\n", status="failed")
    other_script = await script_factory(name="exec_search_stderr_other", content="print(1)")
    await execution_factory(script_id=other_script.id, stderr="clean output", status="success")

    r = await test_client.get("/api/executions", params={"search": "error_marker_token_q2"})
    assert r.status_code == 200
    body = r.json()
    items = body.get("items", body) if isinstance(body, dict) else body
    assert len(items) == 1
    assert items[0]["script_id"] == script.id


@pytest.mark.asyncio
async def test_executions_search_matches_script_name(
    test_client, script_factory, execution_factory
):
    """Search by a script name finds all its executions even if their output is empty."""
    script = await script_factory(name="named_marker_script", content="print(1)")
    await execution_factory(script_id=script.id, stdout="", status="success")
    other_script = await script_factory(name="unrelated_script", content="print(1)")
    await execution_factory(script_id=other_script.id, stdout="anything", status="success")

    r = await test_client.get("/api/executions", params={"search": "named_marker_script"})
    assert r.status_code == 200
    items = r.json().get("items", r.json())
    script_ids = [e["script_id"] for e in items]
    assert script.id in script_ids
    assert other_script.id not in script_ids


@pytest.mark.asyncio
async def test_search_empty_string_returns_all(test_client, script_factory):
    """Empty search string is a no-op (returns everything), not 422."""
    await script_factory(name="empty_search_a", content="print(1)")
    await script_factory(name="empty_search_b", content="print(2)")

    r = await test_client.get("/api/scripts", params={"search": ""})
    assert r.status_code == 200
    items = r.json().get("items", r.json())
    names = [s.get("name") for s in items]
    assert "empty_search_a" in names
    assert "empty_search_b" in names
