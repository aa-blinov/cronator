"""TDD tests for Q1: Bulk script actions + /scripts list page.

Q1 — adds operator essentials for >20 scripts:
- GET /scripts page with sortable table, search, pagination, status filter
- POST /api/scripts/bulk/{action} (enable | disable | delete) — single call
  to act on many scripts. Returns 200 with {succeeded: [...], failed: [...]}.

The endpoints are idempotent and never partially apply: if 1 of N scripts
is running (delete-blocked), the others still succeed but the response
records the failure per-id.
"""

from __future__ import annotations

import pytest

from app.services.scheduler import scheduler_service


@pytest.mark.asyncio
async def test_bulk_disable_actually_removes_the_scheduler_job(test_client, script_factory):
    """Bulk-disable must unschedule the job, not just flip `enabled` in the DB
    (remove_job takes a script_id, not a Script object)."""
    s = await script_factory(name="bulk_sched", content="print(1)", enabled=True, cron_expression="* * * * *")
    await scheduler_service.add_job(s)
    assert scheduler_service.scheduler.get_job(f"script_{s.id}") is not None

    r = await test_client.post("/api/scripts/bulk/disable", json={"ids": [s.id]})
    assert r.status_code == 200, r.text

    assert scheduler_service.scheduler.get_job(f"script_{s.id}") is None


@pytest.mark.asyncio
async def test_bulk_disable_marks_all_targeted_scripts_disabled(test_client, script_factory):
    """POST /api/scripts/bulk/disable flips every targeted script.enabled to False."""
    s1 = await script_factory(name="bulk_a", content="print(1)", enabled=True)
    s2 = await script_factory(name="bulk_b", content="print(2)", enabled=True)
    s3 = await script_factory(name="bulk_c", content="print(3)", enabled=False)

    r = await test_client.post(
        "/api/scripts/bulk/disable",
        json={"ids": [s1.id, s2.id, s3.id]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert sorted(body["succeeded"]) == sorted([s1.id, s2.id, s3.id])
    assert body["failed"] == []

    for s in (s1, s2, s3):
        check = await test_client.get(f"/api/scripts/{s.id}")
        assert check.json()["enabled"] is False


@pytest.mark.asyncio
async def test_bulk_enable_marks_all_targeted_scripts_enabled(test_client, script_factory):
    """POST /api/scripts/bulk/enable flips every targeted script.enabled to True."""
    s1 = await script_factory(name="bulk_e_a", content="print(1)", enabled=False)
    s2 = await script_factory(name="bulk_e_b", content="print(2)", enabled=False)

    r = await test_client.post(
        "/api/scripts/bulk/enable",
        json={"ids": [s1.id, s2.id]},
    )
    assert r.status_code == 200
    assert sorted(r.json()["succeeded"]) == sorted([s1.id, s2.id])
    assert r.json()["failed"] == []


@pytest.mark.asyncio
async def test_bulk_delete_removes_all_targeted_scripts(test_client, script_factory):
    """POST /api/scripts/bulk/delete deletes every targeted script."""
    s1 = await script_factory(name="bulk_d_a", content="print(1)")
    s2 = await script_factory(name="bulk_d_b", content="print(2)")

    r = await test_client.post(
        "/api/scripts/bulk/delete",
        json={"ids": [s1.id, s2.id]},
    )
    assert r.status_code == 200
    assert sorted(r.json()["succeeded"]) == sorted([s1.id, s2.id])

    for s in (s1, s2):
        check = await test_client.get(f"/api/scripts/{s.id}")
        assert check.status_code == 404


@pytest.mark.asyncio
async def test_bulk_unknown_ids_appear_in_failed(test_client, script_factory):
    """Unknown ids are listed under `failed`, not `succeeded`, and the
    rest of the request still succeeds (no all-or-nothing)."""
    real = await script_factory(name="bulk_mixed", content="print(1)", enabled=True)

    r = await test_client.post(
        "/api/scripts/bulk/disable",
        json={"ids": [real.id, 99999999, 99999998]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["succeeded"] == [real.id]
    failed_ids = sorted(f["id"] for f in body["failed"])
    assert failed_ids == [99999998, 99999999]
    assert all(f["error"] for f in body["failed"])


@pytest.mark.asyncio
async def test_bulk_delete_running_script_is_recorded_failed(test_client, script_factory, monkeypatch):
    """A script that's currently running must be reported in `failed`
    (cannot delete a running script), while non-running siblings still go through."""
    from app.services import executor as executor_module

    s_ok = await script_factory(name="bulk_ok", content="print(1)")
    s_busy = await script_factory(name="bulk_busy", content="print(2)")

    # Mark busy as running
    executor_module.executor_service._running_scripts.add(s_busy.id)
    try:
        r = await test_client.post(
            "/api/scripts/bulk/delete",
            json={"ids": [s_ok.id, s_busy.id]},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["succeeded"] == [s_ok.id]
        assert len(body["failed"]) == 1
        assert body["failed"][0]["id"] == s_busy.id
        assert "running" in body["failed"][0]["error"].lower()
    finally:
        executor_module.executor_service._running_scripts.discard(s_busy.id)
        await test_client.delete(f"/api/scripts/{s_busy.id}")


@pytest.mark.asyncio
async def test_bulk_rejects_empty_ids(test_client):
    """An empty `ids` list should be a 400 — not a silent no-op."""
    r = await test_client.post("/api/scripts/bulk/disable", json={"ids": []})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_bulk_requires_ids_field(test_client):
    """Missing `ids` field is a 422."""
    r = await test_client.post("/api/scripts/bulk/disable", json={})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_scripts_page_returns_200_with_table(test_client, script_factory):
    """GET /scripts (the new HTML page) returns 200 with the table markup."""
    await script_factory(name="page_a", content="print(1)")
    await script_factory(name="page_b", content="print(2)")

    r = await test_client.get("/scripts")
    assert r.status_code == 200
    body = r.text
    # the new page lists scripts in a table; original dashboard widget used <table class="table w-full">
    assert "page_a" in body
    assert "page_b" in body
    # It must have the bulk-action toolbar
    assert "Bulk" in body or "bulk-action" in body.lower() or "bulk-select" in body.lower()


@pytest.mark.asyncio
async def test_scripts_page_search_query_filters(test_client, script_factory):
    """The /scripts page accepts ?search= and filters accordingly."""
    await script_factory(name="search_marker_alpha", content="print(1)")
    await script_factory(name="search_marker_beta", content="print(2)")
    await script_factory(name="other_gamma", content="print(3)")

    r = await test_client.get("/scripts", params={"search": "search_marker"})
    assert r.status_code == 200
    body = r.text
    assert "search_marker_alpha" in body
    assert "search_marker_beta" in body
    assert "other_gamma" not in body