"""Unit tests for executor alert methods: _send_success_alert, _send_failure_alert."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.executor import ExecutorService


def _make_execution(script_id: int = 1) -> MagicMock:
    execution = MagicMock()
    execution.id = 99
    execution.script_id = script_id
    execution.status = "success"
    execution.exit_code = 0
    execution.stderr = ""
    execution.error_message = None
    execution.started_at = datetime.now(UTC)
    execution.duration_formatted = "1s"
    return execution


def _make_script(
    *,
    alert_on_success: bool = False,
    alert_on_failure: bool = False,
    last_alert_at: datetime | None = None,
) -> MagicMock:
    script = MagicMock()
    script.id = 1
    script.name = "test_script"
    script.alert_on_success = alert_on_success
    script.alert_on_failure = alert_on_failure
    script.last_alert_at = last_alert_at
    return script


def _make_db_ctx(script: MagicMock | None) -> MagicMock:
    """Мок сессии БД, возвращающий script из execute()."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = script

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=result)
    mock_db.commit = AsyncMock()

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_db)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


# ─────────────────────────── _send_success_alert ────────────────────────────


class TestSendSuccessAlert:
    """Тесты для ExecutorService._send_success_alert."""

    @pytest.mark.asyncio
    async def test_sends_alert_when_enabled(self):
        """Если alert_on_success=True — алерт отправляется, last_alert_at обновляется."""
        script = _make_script(alert_on_success=True)
        execution = _make_execution()

        mock_send = AsyncMock(return_value=True)

        with (
            patch(
                "app.services.executor.async_session_maker",
                return_value=_make_db_ctx(script),
            ),
            patch(
                "app.services.alerting.alerting_service.send_success_alert",
                mock_send,
            ),
        ):
            service = ExecutorService()
            await service._send_success_alert(execution)

        mock_send.assert_awaited_once_with(script, execution)
        assert script.last_alert_at is not None

    @pytest.mark.asyncio
    async def test_does_not_send_when_disabled(self):
        """Если alert_on_success=False — алерт не отправляется."""
        script = _make_script(alert_on_success=False)
        execution = _make_execution()

        mock_send = AsyncMock()

        with (
            patch(
                "app.services.executor.async_session_maker",
                return_value=_make_db_ctx(script),
            ),
            patch(
                "app.services.alerting.alerting_service.send_success_alert",
                mock_send,
            ),
        ):
            service = ExecutorService()
            await service._send_success_alert(execution)

        mock_send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_does_nothing_when_script_not_found(self):
        """Если скрипт не найден в БД — не падает, алерт не отправляется."""
        execution = _make_execution()
        mock_send = AsyncMock()

        with (
            patch(
                "app.services.executor.async_session_maker",
                return_value=_make_db_ctx(script=None),
            ),
            patch(
                "app.services.alerting.alerting_service.send_success_alert",
                mock_send,
            ),
        ):
            service = ExecutorService()
            await service._send_success_alert(execution)  # не должен упасть

        mock_send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_commits_after_alert(self):
        """После отправки алерта должен быть db.commit()."""
        script = _make_script(alert_on_success=True)
        execution = _make_execution()
        db_ctx = _make_db_ctx(script)

        with (
            patch(
                "app.services.executor.async_session_maker",
                return_value=db_ctx,
            ),
            patch(
                "app.services.alerting.alerting_service.send_success_alert",
                AsyncMock(return_value=True),
            ),
        ):
            service = ExecutorService()
            await service._send_success_alert(execution)

        # Достаём mock_db из контекста и проверяем commit
        mock_db = db_ctx.__aenter__.return_value
        mock_db.commit.assert_awaited_once()


# ─────────────────────────── _send_failure_alert ────────────────────────────


class TestSendFailureAlert:
    """Тесты для ExecutorService._send_failure_alert."""

    @pytest.mark.asyncio
    async def test_sends_alert_when_enabled_no_previous_alert(self):
        """alert_on_failure=True, last_alert_at=None → алерт отправляется."""
        script = _make_script(alert_on_failure=True, last_alert_at=None)
        execution = _make_execution()
        mock_send = AsyncMock(return_value=True)

        with (
            patch(
                "app.services.executor.async_session_maker",
                return_value=_make_db_ctx(script),
            ),
            patch(
                "app.services.alerting.alerting_service.send_failure_alert",
                mock_send,
            ),
        ):
            service = ExecutorService()
            await service._send_failure_alert(execution)

        mock_send.assert_awaited_once_with(script, execution)

    @pytest.mark.asyncio
    async def test_throttled_when_last_alert_is_recent(self):
        """Если последний алерт был < 1 часа назад — новый не отправляется (throttling)."""
        recent = datetime.now(UTC) - timedelta(minutes=30)
        script = _make_script(alert_on_failure=True, last_alert_at=recent)
        execution = _make_execution()
        mock_send = AsyncMock()

        with (
            patch(
                "app.services.executor.async_session_maker",
                return_value=_make_db_ctx(script),
            ),
            patch(
                "app.services.alerting.alerting_service.send_failure_alert",
                mock_send,
            ),
        ):
            service = ExecutorService()
            await service._send_failure_alert(execution)

        mock_send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sends_alert_when_last_alert_is_old(self):
        """Если последний алерт был > 1 часа назад — throttling не срабатывает, алерт идёт."""
        old = datetime.now(UTC) - timedelta(hours=2)
        script = _make_script(alert_on_failure=True, last_alert_at=old)
        execution = _make_execution()
        mock_send = AsyncMock(return_value=True)

        with (
            patch(
                "app.services.executor.async_session_maker",
                return_value=_make_db_ctx(script),
            ),
            patch(
                "app.services.alerting.alerting_service.send_failure_alert",
                mock_send,
            ),
        ):
            service = ExecutorService()
            await service._send_failure_alert(execution)

        mock_send.assert_awaited_once_with(script, execution)

    @pytest.mark.asyncio
    async def test_throttled_with_naive_datetime(self):
        """last_alert_at без tzinfo (naive) — всё равно корректно throttle-ится."""
        recent_naive = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=10)
        script = _make_script(alert_on_failure=True, last_alert_at=recent_naive)
        execution = _make_execution()
        mock_send = AsyncMock()

        with (
            patch(
                "app.services.executor.async_session_maker",
                return_value=_make_db_ctx(script),
            ),
            patch(
                "app.services.alerting.alerting_service.send_failure_alert",
                mock_send,
            ),
        ):
            service = ExecutorService()
            await service._send_failure_alert(execution)

        mock_send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_does_not_send_when_disabled(self):
        """alert_on_failure=False → алерт не отправляется."""
        script = _make_script(alert_on_failure=False)
        execution = _make_execution()
        mock_send = AsyncMock()

        with (
            patch(
                "app.services.executor.async_session_maker",
                return_value=_make_db_ctx(script),
            ),
            patch(
                "app.services.alerting.alerting_service.send_failure_alert",
                mock_send,
            ),
        ):
            service = ExecutorService()
            await service._send_failure_alert(execution)

        mock_send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_does_nothing_when_script_not_found(self):
        """Скрипт не найден — не падает, алерт не отправляется."""
        execution = _make_execution()
        mock_send = AsyncMock()

        with (
            patch(
                "app.services.executor.async_session_maker",
                return_value=_make_db_ctx(script=None),
            ),
            patch(
                "app.services.alerting.alerting_service.send_failure_alert",
                mock_send,
            ),
        ):
            service = ExecutorService()
            await service._send_failure_alert(execution)

        mock_send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_updates_last_alert_at_after_send(self):
        """После отправки алерта last_alert_at должен обновиться."""
        script = _make_script(alert_on_failure=True, last_alert_at=None)
        execution = _make_execution()

        with (
            patch(
                "app.services.executor.async_session_maker",
                return_value=_make_db_ctx(script),
            ),
            patch(
                "app.services.alerting.alerting_service.send_failure_alert",
                AsyncMock(return_value=True),
            ),
        ):
            service = ExecutorService()
            before = datetime.now(UTC)
            await service._send_failure_alert(execution)

        assert script.last_alert_at is not None
        assert script.last_alert_at >= before
