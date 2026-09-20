"""The auto_backup_enabled toggle (P0) persists through
POST /api/settings/update and is reflected by GET /api/settings."""

import pytest

pytestmark = pytest.mark.asyncio


class TestAutoBackupSetting:
    async def test_defaults_to_disabled(self, test_client):
        r = await test_client.get("/api/settings")
        assert r.status_code == 200
        assert r.json()["auto_backup_enabled"] is False

    async def test_can_be_enabled_and_persists(self, test_client):
        r = await test_client.post("/api/settings/update", json={"auto_backup_enabled": True})
        assert r.status_code == 200, r.text

        r = await test_client.get("/api/settings")
        assert r.json()["auto_backup_enabled"] is True
