"""P0: automated backups (app/services/backup_service.py) against real
PostgreSQL — SQLite has no COPY protocol, so the dump format can only be
verified for real here (tests/pg/, testcontainers or TEST_DATABASE_URL).

The core claim under test: a file backup_service.create_backup() writes
must round-trip through the EXISTING POST /api/settings/restore-backup
endpoint unchanged — that endpoint's COPY-block parser
(app/api/settings.py) is what this service's output format has to match.
"""

import gzip

import pytest
from sqlalchemy import text

from app.database import Base
from app.services.backup_service import backup_service
from app.services.settings_service import settings_service

pytestmark = pytest.mark.asyncio


async def _truncate_all_tables(db_session) -> None:
    """Simulate the real disaster-recovery scenario a restore targets: an
    empty, freshly-migrated database — not a live DB with the same rows
    still in it (which would just duplicate-key on every COPY)."""
    table_names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    await db_session.execute(text(f"TRUNCATE {table_names} CASCADE"))
    await db_session.commit()


class TestAutoBackupRoundTrip:
    async def test_backup_round_trips_through_restore_endpoint(
        self, test_client, tmp_path, monkeypatch, db_session
    ):
        # Redirect backups_dir to a throwaway tmp dir instead of ./backups.
        monkeypatch.setattr(backup_service, "backups_dir", lambda: tmp_path)

        await settings_service.set("theme", "dracula")

        backup_path = await backup_service.create_backup()
        assert backup_path.exists()
        assert backup_path.name.startswith("auto_")
        assert backup_path.suffix == ".gz"

        with open(backup_path, "rb") as f:
            backup_bytes = f.read()

        # Simulate real disaster recovery: restore targets an empty,
        # freshly-migrated database, not a live one with the same rows
        # still present (which would just duplicate-key on every COPY).
        await _truncate_all_tables(db_session)

        resp = await test_client.post(
            "/api/settings/restore-backup",
            files={"file": ("backup.sql.gz", backup_bytes, "application/gzip")},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is True, body
        assert body["statements_failed"] == 0, body

        settings_service._loaded = False  # force a fresh read from DB
        theme = await settings_service.get("theme")
        assert theme == "dracula"

    async def test_backup_covers_multiple_tables_in_fk_safe_order(
        self, test_client, tmp_path, monkeypatch, script_factory
    ):
        """Scripts reference nothing; script_versions/executions reference
        scripts. If the dump order were wrong, restoring executions before
        their script exists would violate the FK and the restore endpoint
        would report a failed statement."""
        monkeypatch.setattr(backup_service, "backups_dir", lambda: tmp_path)
        await script_factory(name="auto-backup-fk-check")

        backup_path = await backup_service.create_backup()
        dump_text = gzip.decompress(backup_path.read_bytes()).decode("utf-8")

        scripts_pos = dump_text.index("COPY public.scripts ")
        # script_versions/executions/artifacts all FK to scripts.id
        for child_table in ("script_versions", "executions"):
            marker = f"COPY public.{child_table} "
            if marker in dump_text:
                assert dump_text.index(marker) > scripts_pos, (
                    f"{child_table} dumped before its parent scripts table"
                )

    async def test_prunes_old_automated_backups_after_creating_a_new_one(
        self, test_client, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(backup_service, "backups_dir", lambda: tmp_path)
        for _ in range(10):
            await backup_service.create_backup(keep=3)

        remaining = list(tmp_path.glob("auto_*"))
        assert len(remaining) <= 3
