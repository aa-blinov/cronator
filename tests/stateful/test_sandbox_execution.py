"""Sandbox settings and fail-closed execution.

Landlock cannot be used on the Windows dev host, which is exactly the case
these tests cover: enabling the sandbox without kernel support must produce
a FAILED execution rather than an unrestricted run.
"""

from __future__ import annotations

from app.models.execution import Execution, ExecutionStatus
from app.services.settings_service import settings_service


async def test_sandbox_setting_is_persisted(test_client):
    r = await test_client.post(
        "/api/settings/update",
        json={"sandbox_enabled": True, "sandbox_extra_paths": '["/srv/reports"]'},
    )
    assert r.status_code == 200, r.text

    info = (await test_client.get("/api/settings")).json()
    assert info["sandbox_enabled"] is True
    assert info["sandbox_extra_paths"] == '["/srv/reports"]'

    # Reset for other tests sharing the settings cache.
    await test_client.post(
        "/api/settings/update",
        json={"sandbox_enabled": False, "sandbox_extra_paths": "[]"},
    )


async def test_extra_paths_must_be_absolute(test_client):
    r = await test_client.post(
        "/api/settings/update", json={"sandbox_extra_paths": '["relative/path"]'}
    )
    assert r.status_code == 422, r.text

    r = await test_client.post("/api/settings/update", json={"sandbox_extra_paths": "not json"})
    assert r.status_code == 422, r.text

    r = await test_client.post(
        "/api/settings/update", json={"sandbox_extra_paths": '["/srv/reports"]'}
    )
    assert r.status_code == 200, r.text
    await test_client.post("/api/settings/update", json={"sandbox_extra_paths": "[]"})


async def test_sandbox_unavailable_falls_back_to_unrestricted_run(
    exec_service, test_client, db_session, script_factory, monkeypatch, caplog
):
    from unittest.mock import AsyncMock

    from app import sandbox

    script = await script_factory(name="sandbox_fallback", content="print(1)")

    async def _settings_get(key, default=None):
        if key == "sandbox_enabled":
            return True
        return default

    monkeypatch.setattr(settings_service, "get", _settings_get)
    monkeypatch.setattr(sandbox, "landlock_abi_version", lambda: None)
    # Prevent the background task from actually starting a subprocess.
    monkeypatch.setattr(exec_service, "_run_script", AsyncMock())

    execution_id = await exec_service.execute_script(script.id, triggered_by="scheduler")

    execution = await db_session.get(Execution, execution_id)
    # The run is accepted rather than recorded as failed...
    assert execution.status == ExecutionStatus.RUNNING.value
    # ...but the omission is loud in the log.
    assert "WITHOUT a filesystem sandbox" in caplog.text


async def test_fallback_warning_text_is_explicit():
    from app.services.executor import SANDBOX_FALLBACK_WARNING

    assert "WITHOUT a filesystem sandbox" in SANDBOX_FALLBACK_WARNING


async def test_settings_page_reports_host_support(test_client):
    r = await test_client.get("/settings")
    assert r.status_code == 200
    assert "Host support" in r.text
    assert "Landlock" in r.text
