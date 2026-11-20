"""Missed-schedule detection against a real database.

The sweep recomputes expected fires from each enabled script's cron
expression and records an execution row (status "missed") for every expected
moment with no execution row within its coverage window. A persisted cursor
makes it incremental; these tests drive it with a fixed `now` so the windows
are exact.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.execution import Execution, ExecutionStatus
from app.services import missed_runs
from app.services.cleanup_service import get_retention_limits
from app.services.settings_service import settings_service

NOW = datetime(2026, 11, 20, 12, 30, tzinfo=UTC)
THREE_HOURS_AGO = NOW - timedelta(hours=3)


@pytest.fixture(autouse=True)
def _reset_cursor_cache():
    """The settings singleton is shared across tests in the process; its
    cache must not leak a cursor from a previous test into this one."""
    settings_service._cache.pop(missed_runs.CURSOR_KEY, None)
    yield
    settings_service._cache.pop(missed_runs.CURSOR_KEY, None)


async def _seed_hourly_script(script_factory, created_at: datetime, **kwargs):
    return await script_factory(
        name=kwargs.pop("name", "missed_sweep_script"),
        content="print('ok')",
        cron_expression="0 * * * *",
        enabled=kwargs.pop("enabled", True),
        created_at=created_at,
        **kwargs,
    )


async def _missed_rows(db_session, script_id: int) -> list[Execution]:
    result = await db_session.execute(
        select(Execution)
        .where(Execution.script_id == script_id, Execution.status == "missed")
        .order_by(Execution.started_at.asc())
    )
    return list(result.scalars().all())


async def test_expected_fires_without_runs_are_recorded(test_client, db_session, script_factory):
    script = await _seed_hourly_script(script_factory, NOW - timedelta(hours=5))
    await settings_service.set(missed_runs.CURSOR_KEY, THREE_HOURS_AGO.isoformat())

    created = await missed_runs.detect_missed_runs(now=NOW)

    assert created == 3  # 10:00, 11:00 and 12:00 UTC
    rows = await _missed_rows(db_session, script.id)
    assert [r.started_at.hour for r in rows] == [10, 11, 12]
    for row in rows:
        assert row.status == ExecutionStatus.MISSED.value
        assert row.duration_ms == 0
        assert row.finished_at is not None
        assert "Missed schedule" in (row.error_message or "")


async def test_covered_fire_is_not_recorded(
    test_client, db_session, script_factory, execution_factory
):
    script = await _seed_hourly_script(script_factory, NOW - timedelta(hours=5))
    # The 12:00 fire got a run at 12:00:30 — inside the coverage window.
    await execution_factory(
        script_id=script.id,
        status=ExecutionStatus.SUCCESS.value,
        started_at=datetime(2026, 11, 20, 12, 0, 30, tzinfo=UTC),
    )
    await settings_service.set(missed_runs.CURSOR_KEY, THREE_HOURS_AGO.isoformat())

    created = await missed_runs.detect_missed_runs(now=NOW)

    assert created == 2  # only 10:00 and 11:00
    rows = await _missed_rows(db_session, script.id)
    assert [r.started_at.hour for r in rows] == [10, 11]


async def test_disabled_script_is_ignored(test_client, db_session, script_factory):
    await _seed_hourly_script(script_factory, NOW - timedelta(hours=5), enabled=False)
    await settings_service.set(missed_runs.CURSOR_KEY, THREE_HOURS_AGO.isoformat())

    assert await missed_runs.detect_missed_runs(now=NOW) == 0


async def test_fire_before_script_creation_is_ignored(test_client, db_session, script_factory):
    # Created at 12:15 — the 10:00, 11:00 and 12:00 fires predate it.
    await _seed_hourly_script(script_factory, NOW - timedelta(minutes=15))
    await settings_service.set(missed_runs.CURSOR_KEY, THREE_HOURS_AGO.isoformat())

    assert await missed_runs.detect_missed_runs(now=NOW) == 0


async def test_cursor_advances_after_a_sweep(test_client, db_session, script_factory):
    await _seed_hourly_script(script_factory, NOW - timedelta(hours=5))
    await settings_service.set(missed_runs.CURSOR_KEY, THREE_HOURS_AGO.isoformat())

    assert await missed_runs.detect_missed_runs(now=NOW) == 3

    # The second sweep starts where the first ended — nothing new.
    assert await missed_runs.detect_missed_runs(now=NOW) == 0
    rows = await _missed_rows(db_session, (await _first_script(db_session)).id)
    assert len(rows) == 3


async def test_lookback_is_clamped_to_seven_days(test_client, db_session, script_factory):
    await script_factory(
        name="missed_daily_script",
        content="print('ok')",
        cron_expression="0 0 * * *",
        enabled=True,
        created_at=NOW - timedelta(days=40),
    )
    # A cursor a month old must not replay the whole month.
    await settings_service.set(missed_runs.CURSOR_KEY, (NOW - timedelta(days=30)).isoformat())

    created = await missed_runs.detect_missed_runs(now=NOW)

    # Daily cron, window clamped to [NOW-7d, NOW-120s] → 7 fires.
    assert created == 7


async def test_failure_alert_sent_once_per_sweep(
    test_client, db_session, script_factory, monkeypatch
):
    script = await _seed_hourly_script(script_factory, NOW - timedelta(hours=5))
    await settings_service.set(missed_runs.CURSOR_KEY, THREE_HOURS_AGO.isoformat())

    from app.services.alerting import alerting_service

    sent: list[tuple[str, str]] = []

    async def _record_alert(script_obj, execution):
        sent.append((script_obj.name, execution.status))

    monkeypatch.setattr(alerting_service, "send_failure_alert", _record_alert)

    await missed_runs.detect_missed_runs(now=NOW)

    # One alert for three misses, judged on the newest one.
    assert sent == [(script.name, ExecutionStatus.MISSED.value)]

    # The throttle column was written by the sweep's own session — reload
    # rather than trust the factory's stale instance.
    script_id = script.id  # captured before expiring, while attrs are loaded
    db_session.expire_all()
    from app.models.script import Script

    fresh = await db_session.get(Script, script_id)
    assert fresh.last_failure_alert_at is not None


async def test_failure_alert_throttled_within_an_hour(
    test_client, db_session, script_factory, monkeypatch
):
    from app.models.script import Script as ScriptModel

    await _seed_hourly_script(script_factory, NOW - timedelta(hours=5))
    await settings_service.set(missed_runs.CURSOR_KEY, THREE_HOURS_AGO.isoformat())

    from app.services.alerting import alerting_service

    calls: list[str] = []

    async def _record_alert(script_obj, execution):
        calls.append(script_obj.name)

    monkeypatch.setattr(alerting_service, "send_failure_alert", _record_alert)

    # The throttle column already holds a fresh timestamp — no alert allowed.
    from app.database import async_session_maker

    async with async_session_maker() as db:
        script = (await db.execute(select(ScriptModel))).scalar_one()
        script.last_failure_alert_at = NOW - timedelta(minutes=30)
        await db.commit()

    await missed_runs.detect_missed_runs(now=NOW)
    assert calls == []


async def test_missed_status_has_a_retention_limit():
    assert get_retention_limits()[ExecutionStatus.MISSED.value] >= 1


async def test_missed_today_surfaces_in_dashboard_attention(
    test_client, script_factory, execution_factory
):
    script = await script_factory(name="dash_missed", content="print(1)", enabled=True)
    await execution_factory(
        script_id=script.id,
        status=ExecutionStatus.MISSED.value,
        started_at=datetime.now(UTC),
    )

    r = await test_client.get("/")
    assert r.status_code == 200
    assert "Missed Schedules Today" in r.text
    attention_html = r.text.partition("Requires Attention")[2].split("<!-- Scripts Table -->")[0]
    assert "dash_missed" in attention_html


async def _first_script(db_session):
    from app.models.script import Script

    return (await db_session.execute(select(Script))).scalar_one()
