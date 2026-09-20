"""Retention logic for automated backups (app/services/backup_service.py).
Pure filesystem test — no DB needed."""

import time

import app.main  # noqa: F401 - forces model/db import order before services
from app.services.backup_service import BackupService


class TestBackupPruning:
    def test_keeps_only_n_most_recent_auto_backups(self, tmp_path):
        svc = BackupService()
        for i in range(10):
            f = tmp_path / f"auto_2026010{i}_000000.sql.gz"
            f.write_bytes(b"x")
            # distinct mtimes, oldest first
            mtime = time.time() - (10 - i)
            import os

            os.utime(f, (mtime, mtime))

        svc._prune_old_backups(tmp_path, keep=3)

        remaining = sorted(p.name for p in tmp_path.glob("auto_*"))
        assert len(remaining) == 3
        # the 3 most recently created ones survive
        assert remaining == [
            "auto_20260107_000000.sql.gz",
            "auto_20260108_000000.sql.gz",
            "auto_20260109_000000.sql.gz",
        ]

    def test_never_touches_manual_backups(self, tmp_path):
        svc = BackupService()
        manual = tmp_path / "manual_20260101.sql.gz"
        manual.write_bytes(b"x")
        for i in range(5):
            f = tmp_path / f"auto_{i}.sql.gz"
            f.write_bytes(b"x")

        svc._prune_old_backups(tmp_path, keep=1)

        assert manual.exists()
