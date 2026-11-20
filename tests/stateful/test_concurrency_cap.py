"""Concurrency cap and in-uptime stale-execution sweep.

Both are about the same failure mode: too many live runs on a small host,
or a run that is recorded as RUNNING after its process is gone. Neither
needs a queue or a worker — they are a setting and a periodic sweep.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models.execution import Execution, ExecutionStatus
from app.services.settings_service import settings_service


async def test_scheduled_fire_over_cap_is_recorded_as_skipped(
    exec_service, test_client, script_factory, db_session, monkeypatch
):
    script = await script_factory(name="cap_script", content="print(1)")

    def _settings_get(key, default=None):
        if key == "max_concurrent_executions":
            return 1
        return default

    monkeypatch.setattr(settings_service, "get_cached", _settings_get)
    # Simulate another live run without actually starting a subprocess.
    exec_service._running_scripts.add(999999)

    execution_id = await exec_service.execute_script(script.id, triggered_by="scheduler")

    execution = await db_session.get(Execution, execution_id)
    assert execution.status == ExecutionStatus.SKIPPED.value
    assert "max_concurrent_executions=1" in (execution.stdout or "")

    exec_service._running_scripts.discard(999999)


async def test_setting_accepts_a_cap_and_rejects_nonsense(test_client):
    r = await test_client.post("/api/settings/update", json={"max_concurrent_executions": 3})
    assert r.status_code == 200, r.text
    info = await test_client.get("/api/settings")
    assert info.json()["max_concurrent_executions"] == 3

    r = await test_client.post("/api/settings/update", json={"max_concurrent_executions": 101})
    assert r.status_code == 422

    # Leave the cache clean for other tests in the process.
    await test_client.post("/api/settings/update", json={"max_concurrent_executions": 0})


async def test_stale_sweep_marks_only_lost_rows(
    exec_service, test_client, db_session, script_factory, execution_factory
):
    script = await script_factory(name="stale_sweep_script", content="print(1)", timeout=60)

    lost = await execution_factory(
        script_id=script.id,
        status=ExecutionStatus.RUNNING.value,
        started_at=datetime.now(UTC) - timedelta(hours=2),
    )
    fresh = await execution_factory(
        script_id=script.id,
        status=ExecutionStatus.RUNNING.value,
        started_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    lost_id, fresh_id = lost.id, fresh.id  # captured before expiring the session

    marked = await exec_service.sweep_stale_running_executions()
    assert marked == 1

    db_session.expire_all()
    lost_row = await db_session.get(Execution, lost_id)
    fresh_row = await db_session.get(Execution, fresh_id)
    assert lost_row.status == ExecutionStatus.FAILED.value
    assert "no live process" in (lost_row.error_message or "")
    assert lost_row.finished_at is not None
    assert fresh_row.status == ExecutionStatus.RUNNING.value


async def test_stale_sweep_respects_a_live_process(
    exec_service, test_client, db_session, script_factory, execution_factory
):
    from types import SimpleNamespace

    script = await script_factory(name="live_sweep_script", content="print(1)", timeout=60)
    running = await execution_factory(
        script_id=script.id,
        status=ExecutionStatus.RUNNING.value,
        started_at=datetime.now(UTC) - timedelta(hours=2),
    )
    running_id = running.id
    exec_service.running_processes[running.id] = SimpleNamespace()

    try:
        assert await exec_service.sweep_stale_running_executions() == 0
        db_session.expire_all()
        row = await db_session.get(Execution, running_id)
        assert row.status == ExecutionStatus.RUNNING.value
    finally:
        exec_service.running_processes.pop(running.id, None)
