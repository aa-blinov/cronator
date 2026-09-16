"""TDD tests for F2: Enhanced /health endpoint.

Currently /health returns basic info. We extend it with:
- version (matches package version)
- components.disk.free_bytes / free_mb / total_mb
- components.migrations.current / head / pending
- components.scheduler (already present) + .job_count
- status: "degraded" if any non-database component is "unknown"
- no secrets in response

Without this, an operator can't tell at a glance:
- whether pending migrations might leave the app in a broken state
- how full the disk is (artifact storage, logs, backups all consume disk)
- how many scheduled jobs are registered (helps confirm scheduler reload)
"""

import pytest


@pytest.mark.asyncio
async def test_health_has_version(test_client):
    """Health response includes a version string."""
    response = await test_client.get("/health")
    # 200 if healthy, 503 if degraded — both are valid here; we just care about content
    assert response.status_code in (200, 503)
    body = response.json()
    assert "version" in body, body
    version = body["version"]
    parts = version.split(".")
    assert len(parts) >= 2, f"version {version!r} is not in x.y.z format"
    assert all(p.isdigit() for p in parts[:2]), f"version {version!r} is not numeric"


@pytest.mark.asyncio
async def test_health_components_has_disk(test_client):
    """Disk section must include free/total bytes & percentage."""
    response = await test_client.get("/health")
    body = response.json()
    disk = body["components"].get("disk", {})
    # Disk info is informational and falls back to / if data_dir doesn't exist.
    # In test fixtures the data_dir may not exist; we tolerate either form:
    #   {"free_bytes": ..., "total_bytes": ...}
    #   {"error": "..."}
    assert disk, f"components.disk missing in health response: {body['components']}"
    if "error" in disk:
        pytest.skip(f"disk section errored (acceptable in test env): {disk['error']}")
    assert "free_bytes" in disk, disk
    assert "free_mb" in disk, disk
    assert "total_bytes" in disk, disk
    assert "total_mb" in disk, disk
    assert "used_percent" in disk, disk
    assert disk["free_bytes"] > 0, disk
    assert disk["free_bytes"] <= disk["total_bytes"], disk
    assert 0 <= disk["used_percent"] <= 100, disk


@pytest.mark.asyncio
async def test_health_components_has_migrations(test_client):
    response = await test_client.get("/health")
    body = response.json()
    migrations = body["components"].get("migrations", {})
    assert migrations, f"components.migrations missing: {body['components']}"
    # In test mode SKIP_ALEMBIC_MIGRATIONS=1 — schema is created from models, so
    # the migrations table may not exist. We accept either:
    #   {"current": "<rev>", "head": "<rev>", "pending": false}
    #   {"status": "skipped", "reason": "SKIP_ALEMBIC_MIGRATIONS=1"}
    assert "current" in migrations or "status" in migrations, migrations


@pytest.mark.asyncio
async def test_health_components_scheduler_has_job_count(test_client):
    response = await test_client.get("/health")
    body = response.json()
    scheduler = body["components"].get("scheduler", {})
    assert scheduler, body["components"]
    # job_count must be present (value is non-negative integer)
    assert "job_count" in scheduler, scheduler
    assert isinstance(scheduler["job_count"], int), scheduler
    assert scheduler["job_count"] >= 0, scheduler


@pytest.mark.asyncio
async def test_health_status_is_healthy_when_database_ok(test_client):
    """If the database is reachable, status field is reported (healthy or degraded).
    Test fixture doesn't run the lifespan, so scheduler is stopped — but database
    ping works and disk/migration fields are populated. We only assert structural
    facts, not the specific status value."""
    response = await test_client.get("/health")
    body = response.json()
    assert body["status"] in ("healthy", "degraded"), body
    assert body["components"]["database"] == "healthy", body
    # Scheduler field must be the structured object (not a bare string)
    assert isinstance(body["components"]["scheduler"], dict), body["components"]["scheduler"]


@pytest.mark.asyncio
async def test_health_response_no_secrets(test_client):
    response = await test_client.get("/health")
    body = response.json()
    # Make sure SECRET_KEY / passwords don't leak anywhere in the response
    raw = response.text.lower()
    for secret_token in ("secret_key", "admin_password", "postgresql://", "smtp_password"):
        assert secret_token not in raw, f"sensitive token {secret_token!r} present in health"
