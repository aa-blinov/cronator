"""Backup archive verification + last-backup status (app/services/backup_service.py).

Pure filesystem tests — no DB needed. Guards the failure mode where a dump
silently produces an empty/truncated archive that only fails at restore time.
"""

import gzip

import pytest

import app.main  # noqa: F401 - forces model/db import order before services
from app.services.backup_service import BackupService, get_last_backup_status


class TestVerifyBackup:
    def test_rejects_missing_archive(self, tmp_path):
        svc = BackupService()
        with pytest.raises(RuntimeError):
            svc._verify_backup(tmp_path / "does-not-exist.sql.gz")

    def test_rejects_empty_archive(self, tmp_path):
        svc = BackupService()
        empty = tmp_path / "auto_empty.sql.gz"
        empty.write_bytes(b"")
        with pytest.raises(RuntimeError):
            svc._verify_backup(empty)

    def test_rejects_non_gzip_archive(self, tmp_path):
        svc = BackupService()
        bad = tmp_path / "auto_bad.sql.gz"
        bad.write_bytes(b"this is not gzip")
        with pytest.raises(RuntimeError):
            svc._verify_backup(bad)

    def test_accepts_valid_gzip(self, tmp_path):
        svc = BackupService()
        good = tmp_path / "auto_20260101_000000.sql.gz"
        good.write_bytes(gzip.compress(b"COPY public.scripts (id) FROM stdin;\n\\.\n"))
        svc._verify_backup(good)  # must not raise


def test_get_last_backup_status_returns_a_copy():
    status = get_last_backup_status()
    assert set(status) >= {"status", "path", "size_bytes", "at", "error"}
    status["status"] = "mutated"
    assert get_last_backup_status()["status"] != "mutated"
