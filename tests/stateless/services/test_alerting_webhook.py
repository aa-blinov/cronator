"""F17 was supposed to fire a webhook on script failure, but Settings only
ever offered a "Test Webhook" button — nothing called it when a script
actually failed or succeeded. These tests cover AlertingService.send_webhook
and its wiring into send_failure_alert / send_success_alert.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.alerting import AlertingService


def _script() -> MagicMock:
    script = MagicMock()
    script.id = 1
    script.name = "webhook_test_script"
    return script


def _execution() -> MagicMock:
    execution = MagicMock()
    execution.id = 42
    execution.status = "failed"
    execution.exit_code = 1
    execution.duration_formatted = "2s"
    execution.started_at = datetime.now(UTC)
    execution.error_message = None
    execution.stderr = ""
    return execution


@pytest.mark.asyncio
async def test_send_webhook_posts_payload_when_url_configured():
    service = AlertingService()
    mock_response = MagicMock(status_code=200)
    mock_response.raise_for_status = MagicMock()

    with (
        patch(
            "app.services.settings_service.settings_service.get",
            AsyncMock(return_value="https://example.com/hook"),
        ),
        patch("httpx.AsyncClient.post", AsyncMock(return_value=mock_response)) as mock_post,
    ):
        ok = await service.send_webhook("execution_failed", _script(), _execution())

    assert ok is True
    mock_post.assert_awaited_once()
    url, kwargs = mock_post.call_args.args[0], mock_post.call_args.kwargs
    assert url == "https://example.com/hook"
    assert kwargs["json"]["type"] == "execution_failed"
    assert kwargs["json"]["script"]["name"] == "webhook_test_script"
    assert kwargs["json"]["execution"]["id"] == 42


@pytest.mark.asyncio
async def test_send_webhook_is_noop_when_not_configured():
    service = AlertingService()
    with (
        patch(
            "app.services.settings_service.settings_service.get",
            AsyncMock(return_value=""),
        ),
        patch("httpx.AsyncClient.post", AsyncMock()) as mock_post,
    ):
        ok = await service.send_webhook("execution_failed", _script(), _execution())

    assert ok is False
    mock_post.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_webhook_failure_does_not_raise():
    """A dead/unreachable webhook endpoint must not break alerting."""
    service = AlertingService()
    with (
        patch(
            "app.services.settings_service.settings_service.get",
            AsyncMock(return_value="https://example.com/hook"),
        ),
        patch(
            "httpx.AsyncClient.post",
            AsyncMock(side_effect=httpx.ConnectError("refused")),
        ),
    ):
        ok = await service.send_webhook("execution_failed", _script(), _execution())

    assert ok is False


@pytest.mark.asyncio
async def test_failure_alert_also_fires_webhook():
    service = AlertingService()
    with (
        patch.object(service, "send_email", AsyncMock(return_value=True)),
        patch.object(service, "send_webhook", AsyncMock(return_value=True)) as mock_webhook,
    ):
        await service.send_failure_alert(_script(), _execution())

    mock_webhook.assert_awaited_once()
    assert mock_webhook.call_args.args[0] == "execution_failed"


@pytest.mark.asyncio
async def test_success_alert_also_fires_webhook():
    service = AlertingService()
    with (
        patch.object(service, "send_email", AsyncMock(return_value=True)),
        patch.object(service, "send_webhook", AsyncMock(return_value=True)) as mock_webhook,
    ):
        await service.send_success_alert(_script(), _execution())

    mock_webhook.assert_awaited_once()
    assert mock_webhook.call_args.args[0] == "execution_succeeded"
