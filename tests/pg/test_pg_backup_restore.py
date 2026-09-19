"""Regression coverage for POST /api/settings/restore-backup against real
PostgreSQL — SQLite can't exercise this at all (no COPY protocol, no
asyncpg), so this only runs where tests/pg/ runs (postgres via
TEST_DATABASE_URL or testcontainers).

Two real bugs found while auditing this endpoint, both fixed in
app/api/settings.py:

1. pg_dump's data section is `COPY ... FROM stdin` followed by raw
   tab-separated rows, not INSERTs. Splitting the SQL text on `;\n` tears
   the COPY header away from its data — sent through db.execute(), that
   either hangs the connection forever waiting for COPY-protocol data
   that will never arrive (confirmed live: pg_stat_activity showed the
   session stuck at wait_event=ClientRead on the COPY statement), or the
   header/data split lands such that the header alone errors out and
   every row in the backup is silently dropped while the endpoint still
   reports `success: true`.

2. pg_dump always opens with
   `SELECT pg_catalog.set_config('search_path', '', false);` — that
   `false` means it's session-scoped, not transaction-scoped. Once that
   statement runs on a pooled connection, EVERY later unqualified query
   on that same connection breaks with "relation does not exist" —
   and the connection goes back to the pool afterward unless it's reset,
   so the breakage isn't confined to the restore request; it's whichever
   unrelated request happens to check that connection out next.
"""

import gzip

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


def _synthetic_backup(rows: list[tuple[str, str, str]]) -> bytes:
    """A minimal but structurally real pg_dump-style backup: the same
    session-wide search_path reset pg_dump always emits, plus one COPY
    block. No CREATE TABLE needed — test_engine already created the
    schema, matching how a real restore always targets an existing
    schema on a running app.
    """
    data_lines = "\n".join(f"{k}\t{v}\t{d}" for k, v, d in rows)
    sql = (
        "SET statement_timeout = 0;\n"
        "SELECT pg_catalog.set_config('search_path', '', false);\n"
        "COPY public.settings (key, value, description) FROM stdin;\n"
        f"{data_lines}\n"
        "\\.\n"
    )
    return gzip.compress(sql.encode("utf-8"))


class TestRestoreBackupCopyHandling:
    async def test_restore_loads_copy_block_rows(self, test_client: AsyncClient):
        backup = _synthetic_backup(
            [
                ("theme", "dracula", "UI theme"),
                ("locale", "ru", "UI locale"),
            ]
        )

        resp = await test_client.post(
            "/api/settings/restore-backup",
            files={"file": ("backup.sql.gz", backup, "application/gzip")},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["success"] is True
        assert data["statements_failed"] == 0
        assert data["rows_restored"] == 2

    async def test_restore_does_not_hang_or_poison_the_connection_pool(
        self, test_client: AsyncClient
    ):
        """The real-world failure mode: without a COPY-aware parser this
        request either never returns (hung on the COPY protocol) or
        leaves search_path='' on the connection it used, breaking the
        *next* unrelated request that reuses that pooled connection.
        """
        backup = _synthetic_backup([("webhook_url", "https://example.com/hook", "")])

        restore_resp = await test_client.post(
            "/api/settings/restore-backup",
            files={"file": ("backup.sql.gz", backup, "application/gzip")},
        )
        assert restore_resp.status_code == 200, restore_resp.text

        # Any ordinary unqualified-table query, on a (likely reused)
        # pooled connection, must still resolve normally after restore.
        scripts_resp = await test_client.get("/api/scripts")
        assert scripts_resp.status_code == 200, scripts_resp.text

        settings_resp = await test_client.get("/api/settings")
        assert settings_resp.status_code == 200, settings_resp.text
