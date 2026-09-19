"""The /scripts table's "Last Run" column used to read only
`last_success_at`, so a script that fails every time showed "—" forever —
indistinguishable from a script that was never run at all.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest


@pytest.mark.asyncio
async def test_last_run_shows_failure_time_when_more_recent_than_success(
    test_client, script_factory
):
    now = datetime.now(UTC)
    script = await script_factory(
        name="always_failing",
        content="print(1)",
        last_success_at=now - timedelta(days=2),
        last_failure_at=now,
    )

    r = await test_client.get("/scripts")
    assert r.status_code == 200
    row = r.text[r.text.index(f'data-script-id="{script.id}"'):]
    row = row[: row.index("</tr>")]
    assert now.strftime("%Y-%m-%d %H:%M") in row


@pytest.mark.asyncio
async def test_last_run_shows_dash_when_never_run(test_client, script_factory):
    script = await script_factory(name="never_run", content="print(1)")

    r = await test_client.get("/scripts")
    assert r.status_code == 200
    row = r.text[r.text.index(f'data-script-id="{script.id}"'):]
    row = row[: row.index("</tr>")]
    assert "—" in row


@pytest.mark.asyncio
async def test_last_run_shows_success_time_when_no_failure(test_client, script_factory):
    now = datetime.now(UTC)
    script = await script_factory(
        name="succeeding",
        content="print(1)",
        last_success_at=now,
    )

    r = await test_client.get("/scripts")
    assert r.status_code == 200
    row = r.text[r.text.index(f'data-script-id="{script.id}"'):]
    row = row[: row.index("</tr>")]
    assert now.strftime("%Y-%m-%d %H:%M") in row
