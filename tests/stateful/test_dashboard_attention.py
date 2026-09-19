"""Dashboard triage: scripts that failed today or haven't run in 7 days
surface in a separate "Requires Attention" section instead of being buried
alphabetically among healthy scripts.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models.execution import ExecutionStatus


@pytest.mark.asyncio
async def test_script_failed_today_appears_in_attention_section(
    test_client, script_factory, execution_factory
):
    healthy = await script_factory(name="dash_healthy", content="print(1)", enabled=True)
    await execution_factory(
        script_id=healthy.id,
        status=ExecutionStatus.SUCCESS.value,
        started_at=datetime.now(UTC),
    )

    failing = await script_factory(name="dash_failing", content="print(1)", enabled=True)
    await execution_factory(
        script_id=failing.id,
        status=ExecutionStatus.FAILED.value,
        started_at=datetime.now(UTC),
    )

    r = await test_client.get("/")
    assert r.status_code == 200
    body = r.text

    assert "Requires Attention" in body
    attention_section, _, rest = body.partition("Requires Attention")
    assert "dash_failing" in rest.split("<!-- Scripts Table -->")[0]
    # the healthy script must not be counted as needing attention
    attention_html = rest.split("<!-- Scripts Table -->")[0]
    assert "dash_healthy" not in attention_html


@pytest.mark.asyncio
async def test_enabled_script_with_no_recent_run_appears_in_attention_section(
    test_client, script_factory, execution_factory
):
    stale = await script_factory(name="dash_stale", content="print(1)", enabled=True)
    await execution_factory(
        script_id=stale.id,
        status=ExecutionStatus.SUCCESS.value,
        started_at=datetime.now(UTC) - timedelta(days=10),
    )

    r = await test_client.get("/")
    assert r.status_code == 200
    attention_html = r.text.partition("Requires Attention")[2].split("<!-- Scripts Table -->")[0]
    assert "dash_stale" in attention_html


@pytest.mark.asyncio
async def test_disabled_script_never_run_is_not_flagged(test_client, script_factory):
    """A disabled script with no runs is expected to be idle, not unhealthy."""
    await script_factory(name="dash_disabled_idle", content="print(1)", enabled=False)

    r = await test_client.get("/")
    assert r.status_code == 200
    body = r.text
    if "Requires Attention" in body:
        attention_html = body.partition("Requires Attention")[2].split("<!-- Scripts Table -->")[0]
        assert "dash_disabled_idle" not in attention_html
