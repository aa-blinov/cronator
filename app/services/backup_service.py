"""Automated database backup (P0).

Backups were entirely manual before this (docs/OPERATIONS.md —
`docker compose exec db pg_dump ... | gzip > backups/...`). This mirrors
that same COPY-block format so a file this service writes round-trips
through the existing `POST /api/settings/restore-backup` endpoint
unchanged: one `COPY public.<table> (cols) FROM stdin;` block per table
(in FK-safe order via SQLAlchemy's topologically sorted table metadata),
pg_dump-style tab-separated rows, terminated by `\\.`, gzipped.

Like restore-backup, this deliberately avoids shelling out to `pg_dump` —
it isn't on PATH in the runtime image — and uses the same asyncpg COPY
protocol via the app's own async engine instead. SQLite deployments (dev/
test only; see docs/SECURITY.md) have no COPY protocol to mirror, so they
just get a gzip of the .db file.
"""

from __future__ import annotations

import gzip
import io
import logging
from datetime import UTC, datetime
from pathlib import Path

from app.config import get_settings
from app.database import Base, async_session_maker

logger = logging.getLogger(__name__)


class BackupService:
    def backups_dir(self) -> Path:
        settings = get_settings()
        backups_dir = Path("/app/backups") if Path("/app").exists() else Path("./backups")
        if not backups_dir.exists():
            backups_dir = Path(settings.data_dir).parent / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        return backups_dir

    async def create_backup(self, keep: int = 7) -> Path:
        """Write a gzipped backup and prune old automated backups beyond
        `keep`. Returns the path of the file just written."""
        settings = get_settings()
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        backups_dir = self.backups_dir()

        # Branch on the *actual* connected engine's dialect, not the
        # static DATABASE_URL config — tests override async_session_maker's
        # bind directly (see tests/pg/conftest.py) without touching the env
        # var, so a config-string check would silently dump the wrong DB.
        if async_session_maker.kw["bind"].dialect.name == "sqlite":
            dest = backups_dir / f"auto_{timestamp}.db.gz"
            db_path = Path(settings.database_url.replace("sqlite+aiosqlite:///", ""))
            dest.write_bytes(gzip.compress(db_path.read_bytes()))
        else:
            dest = backups_dir / f"auto_{timestamp}.sql.gz"
            dest.write_bytes(gzip.compress((await self._dump_postgres()).encode("utf-8")))

        self._prune_old_backups(backups_dir, keep)
        return dest

    async def _dump_postgres(self) -> str:
        parts = [
            "SET statement_timeout = 0;\n",
            "SELECT pg_catalog.set_config('search_path', '', false);\n",
        ]
        async with async_session_maker() as db:
            conn = await db.connection()
            adapted = await conn.get_raw_connection()
            for table in Base.metadata.sorted_tables:
                columns = list(table.columns.keys())
                buf = io.BytesIO()
                await adapted.driver_connection.copy_from_table(
                    table.name, output=buf, format="text"
                )
                parts.append(f"COPY public.{table.name} ({', '.join(columns)}) FROM stdin;\n")
                parts.append(buf.getvalue().decode("utf-8"))
                parts.append("\\.\n")
        return "".join(parts)

    def _prune_old_backups(self, backups_dir: Path, keep: int) -> None:
        """Only prune backups this service created (`auto_*`) — never
        touch manually-made ones a human is relying on."""
        autos = sorted(
            backups_dir.glob("auto_*"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        for stale in autos[keep:]:
            try:
                stale.unlink()
            except OSError:
                logger.warning(f"Failed to prune old backup {stale}")


backup_service = BackupService()
