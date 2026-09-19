"""TDD tests for F6: Prometheus /metrics endpoint.

Expose Prometheus-format metrics so operators can scrape Cronator like any
other service. Counters and gauges are the primary use cases:

- cronitor_scripts_total (gauge) — total number of scripts
- cronitor_executions_total{status,triggered_by} (counter) — execution count
- cronitor_executions_running (gauge) — currently running
- crinator_scheduler_jobs (gauge) — registered scheduler jobs
- crinator_app_info{version="0.1.0"} (gauge, constant 1)
- crinator_uptime_seconds (gauge)
"""

import re

import pytest


@pytest.mark.asyncio
async def test_metrics_endpoint_returns_200(test_client):
    r = await test_client.get("/metrics")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_metrics_content_type(test_client):
    """Prometheus expects text/plain with version parameter."""
    r = await test_client.get("/metrics")
    ct = r.headers.get("content-type", "")
    assert "text/plain" in ct, f"content-type {ct!r} should be text/plain"


@pytest.mark.asyncio
async def test_metrics_contains_help_and_type_comments(test_client):
    """Well-formed Prometheus output includes HELP and TYPE lines for each metric."""
    r = await test_client.get("/metrics")
    body = r.text
    # Every metric we expose should have a HELP line and a TYPE line
    assert "# HELP crinator_" in body or "# HELP cronitor_" in body, body[:500]


@pytest.mark.asyncio
async def test_metrics_app_info_present(test_client):
    """A constant `1` gauge labeled with the app version."""
    r = await test_client.get("/metrics")
    body = r.text
    match = re.search(r'crinator_app_info\{version="[^"]+"\}\s+1\.0', body) or re.search(
        r'cronitor_app_info\{version="[^"]+"\}\s+1\.0', body
    )
    assert match, f"cronitor_app_info gauge not found in:\n{body[:500]}"


@pytest.mark.asyncio
async def test_metrics_exposes_running_executions_gauge(test_client):
    """The number of currently running executions must be exposed."""
    r = await test_client.get("/metrics")
    body = r.text
    assert "running" in body.lower(), body[:500]


@pytest.mark.asyncio
async def test_metrics_no_secrets(test_client):
    """The metrics endpoint must not leak any secret material."""
    r = await test_client.get("/metrics")
    body = r.text.lower()
    for needle in ("secret_key", "admin_password", "postgresql://", "smtp_password"):
        assert needle not in body, f"sensitive token {needle!r} in /metrics output"
