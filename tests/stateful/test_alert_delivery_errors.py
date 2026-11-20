"""Alert delivery failures must be visible on the script, not only in the
application log. The alerting service notes failures per send attempt; the
executor persists them onto the script row; the script page shows them.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.services.alerting import alerting_service


async def _fresh_script(db_session):
    from sqlalchemy import select

    from app.models.script import Script

    return (await db_session.execute(select(Script))).scalar_one()


async def test_failed_email_delivery_lands_on_script(
    exec_service, test_client, db_session, script_factory, execution_factory, monkeypatch
):
    script = await script_factory(
        name="alert_err_script", content="print(1)", alert_on_failure=True
    )
    execution = await execution_factory(script_id=script.id)

    async def _broken_email(subject, body_html, body_text=None):
        alerting_service.note_delivery_error("email: SMTP auth failed")
        return False

    monkeypatch.setattr(alerting_service, "send_email", _broken_email)

    await exec_service._send_failure_alert(execution)

    db_session.expire_all()
    fresh = await _fresh_script(db_session)
    assert "SMTP auth failed" in (fresh.last_alert_error or ""), fresh.last_alert_error
    assert fresh.last_alert_error_at is not None


async def test_failed_webhook_delivery_lands_on_script(
    exec_service, test_client, db_session, script_factory, execution_factory, monkeypatch
):
    script = await script_factory(
        name="alert_wh_err_script", content="print(1)", alert_on_failure=True
    )
    execution = await execution_factory(script_id=script.id)

    async def _broken_webhook(event_type, script_obj, execution_obj):
        alerting_service.note_delivery_error("webhook: HTTP 500")
        return False

    async def _ok_email(subject, body_html, body_text=None):
        return True

    monkeypatch.setattr(alerting_service, "send_email", _ok_email)
    monkeypatch.setattr(alerting_service, "send_webhook", _broken_webhook)

    await exec_service._send_failure_alert(execution)

    db_session.expire_all()
    fresh = await _fresh_script(db_session)
    assert "HTTP 500" in (fresh.last_alert_error or "")


async def test_successful_delivery_clears_previous_error(
    exec_service, test_client, db_session, script_factory, execution_factory, monkeypatch
):
    script = await script_factory(name="alert_ok_script", content="print(1)", alert_on_failure=True)
    # A stale error from an earlier attempt exists on the row.
    script.last_alert_error = "email: old failure"
    script.last_alert_error_at = datetime.now(UTC)
    await db_session.commit()
    execution = await execution_factory(script_id=script.id)

    async def _ok_email(subject, body_html, body_text=None):
        return True

    async def _no_webhook(event_type, script_obj, execution_obj):
        return False

    monkeypatch.setattr(alerting_service, "send_email", _ok_email)
    monkeypatch.setattr(alerting_service, "send_webhook", _no_webhook)

    await exec_service._send_failure_alert(execution)

    db_session.expire_all()
    fresh = await _fresh_script(db_session)
    assert fresh.last_alert_error is None
    assert fresh.last_alert_error_at is None


async def test_script_api_exposes_alert_error(test_client, script_factory, db_session):
    script = await script_factory(name="alert_api_script", content="print(1)")
    script.last_alert_error = "email: boom"
    await db_session.commit()

    r = await test_client.get(f"/api/scripts/{script.id}")
    assert r.status_code == 200
    assert r.json()["last_alert_error"] == "email: boom"


async def test_script_page_renders_alert_error(test_client, script_factory, db_session):
    from datetime import UTC, timedelta

    script = await script_factory(name="alert_page_script", content="print(1)")
    script.last_alert_error = "email: SMTP refused login"
    script.last_alert_error_at = datetime.now(UTC) - timedelta(minutes=5)
    await db_session.commit()

    r = await test_client.get(f"/scripts/{script.id}")
    assert r.status_code == 200
    assert "SMTP refused login" in r.text
    assert "Last Alert Error" in r.text
