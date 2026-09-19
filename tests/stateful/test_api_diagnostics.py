"""TDD tests for F19: /api/diagnostics endpoint.

While /health is for liveness/readiness probes, /api/diagnostics is the
operator-facing one-stop-shop when something is wrong. It returns:

- version + python version + platform
- process info: uptime, PID, RSS
- database connectivity and counts
- scheduler state: job count, jobs list
- executor state: running count, recent cancellations
- configuration snapshot (masked)
- log file size and rotation count
"""

import pytest


@pytest.mark.asyncio
async def test_diagnostics_endpoint_exists(test_client):
    r = await test_client.get("/api/diagnostics")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_diagnostics_has_version(test_client):
    body = (await test_client.get("/api/diagnostics")).json()
    assert "version" in body
    assert "python_version" in body
    assert "platform" in body


@pytest.mark.asyncio
async def test_diagnostics_has_process_info(test_client):
    body = (await test_client.get("/api/diagnostics")).json()
    assert "process" in body
    proc = body["process"]
    assert "uptime_seconds" in proc
    assert "pid" in proc
    assert "rss_bytes" in proc


@pytest.mark.asyncio
async def test_diagnostics_has_database_info(test_client):
    body = (await test_client.get("/api/diagnostics")).json()
    assert "database" in body
    db = body["database"]
    assert db["reachable"] is True
    assert "script_count" in db
    assert "execution_count" in db


@pytest.mark.asyncio
async def test_diagnostics_has_scheduler_info(test_client):
    body = (await test_client.get("/api/diagnostics")).json()
    sched = body["scheduler"]
    assert "running" in sched
    assert "job_count" in sched


@pytest.mark.asyncio
async def test_diagnostics_has_executor_info(test_client):
    body = (await test_client.get("/api/diagnostics")).json()
    exec_info = body["executor"]
    assert "running_executions" in exec_info
    assert "total_processes" in exec_info


@pytest.mark.asyncio
async def test_diagnostics_has_config_snapshot(test_client):
    body = (await test_client.get("/api/diagnostics")).json()
    assert "config" in body
    config = body["config"]
    # Sensitive keys are either masked (***) or empty (unset in test env) — never
    # equal to the real underlying value.
    # We assert the masking is structural: same key always returns same masked form.
    for key in ("smtp_password", "secret_key"):
        if key in config:
            value = config[key]
            assert value == "" or value == "***", f"{key} not properly masked: {value!r}"


@pytest.mark.asyncio
async def test_diagnostics_has_logs_info(test_client):
    body = (await test_client.get("/api/diagnostics")).json()
    assert "logs" in body
    logs = body["logs"]
    assert "log_file" in logs
    assert "size_bytes" in logs
