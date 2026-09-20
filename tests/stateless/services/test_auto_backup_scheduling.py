"""P0: DB backups were entirely manual (docs/OPERATIONS.md — `docker compose
exec db pg_dump ...` by hand). These tests cover the scheduling/toggle
logic in SchedulerService._run_auto_backup: whether it runs
backup_service.create_backup() at all, gated by the `auto_backup_enabled`
setting. The actual COPY-protocol dump format (app/services/backup_service.py)
is exercised for real against PostgreSQL in tests/pg/test_pg_auto_backup.py
— SQLite has no COPY protocol to generate a meaningful dump from.
"""

from unittest.mock import AsyncMock, patch

import pytest

import app.main  # noqa: F401 - forces model/db import order before services
from app.services.scheduler import SchedulerService

pytestmark = pytest.mark.asyncio


class TestAutoBackupScheduling:
    async def test_skips_backup_when_disabled(self):
        svc = SchedulerService()
        with (
            patch("app.services.settings_service.settings_service.get", AsyncMock(return_value=False)),
            patch("app.services.backup_service.backup_service.create_backup", AsyncMock()) as mock_create,
        ):
            await svc._run_auto_backup()
        mock_create.assert_not_called()

    async def test_runs_backup_when_enabled(self):
        svc = SchedulerService()
        with (
            patch("app.services.settings_service.settings_service.get", AsyncMock(return_value=True)),
            patch("app.services.backup_service.backup_service.create_backup", AsyncMock()) as mock_create,
        ):
            await svc._run_auto_backup()
        mock_create.assert_awaited_once()

    async def test_backup_failure_does_not_raise(self):
        """A failed backup must not crash the scheduler's job loop."""
        svc = SchedulerService()
        with (
            patch("app.services.settings_service.settings_service.get", AsyncMock(return_value=True)),
            patch(
                "app.services.backup_service.backup_service.create_backup",
                AsyncMock(side_effect=RuntimeError("disk full")),
            ),
        ):
            await svc._run_auto_backup()  # must not raise
