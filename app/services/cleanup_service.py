"""Execution history cleanup service."""

import logging
import os
import shutil
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select

from app.config import get_settings
from app.database import async_session_maker
from app.models.execution import Execution, ExecutionStatus

logger = logging.getLogger(__name__)

# How many executions to keep per script × status. TIMEOUT is retained like
# FAILED — it's a failure mode, not a terminal state that should be skipped —
# it was missing here entirely, so timed-out executions never got cleaned up
# by the daily job and accumulated in the DB without bound.
RETENTION_BY_STATUS: dict[str, int] = {
    ExecutionStatus.SUCCESS.value: 200,
    ExecutionStatus.FAILED.value: 500,
    ExecutionStatus.TIMEOUT.value: 500,
    ExecutionStatus.SKIPPED.value: 100,
    ExecutionStatus.CANCELLED.value: 100,
}

# Warn when a single cleanup run deletes at least this many rows. A first run
# against a long-neglected DB can legitimately purge tens of thousands — but
# that should be visible in the logs, not silent.
MASS_DELETE_WARNING_THRESHOLD = 1000

# Environment overrides so an operator can keep more history without a code
# change, e.g. EXECUTION_RETENTION_SUCCESS=2000.
_RETENTION_ENV = {
    ExecutionStatus.SUCCESS.value: "EXECUTION_RETENTION_SUCCESS",
    ExecutionStatus.FAILED.value: "EXECUTION_RETENTION_FAILED",
    ExecutionStatus.TIMEOUT.value: "EXECUTION_RETENTION_TIMEOUT",
    ExecutionStatus.SKIPPED.value: "EXECUTION_RETENTION_SKIPPED",
    ExecutionStatus.CANCELLED.value: "EXECUTION_RETENTION_CANCELLED",
}


def get_retention_limits() -> dict[str, int]:
    """Effective per-status retention, with env overrides applied."""
    limits = dict(RETENTION_BY_STATUS)
    for status, env_name in _RETENTION_ENV.items():
        raw = os.getenv(env_name)
        if not raw:
            continue
        try:
            value = int(raw)
        except ValueError:
            logger.warning("Ignoring non-integer %s=%r", env_name, raw)
            continue
        if value < 1:
            logger.warning("Ignoring non-positive %s=%r", env_name, raw)
            continue
        limits[status] = value
    return limits


class CleanupService:
    """Handles automatic and manual cleanup of execution history."""

    async def cleanup_by_status(self) -> dict:
        """
        Status-aware per-script cleanup (automatic daily job).

        For each script × status pair, keeps only the most recent N executions
        (as defined in RETENTION_BY_STATUS) and deletes the rest, including
        their artifact directories.
        """
        cfg = get_settings()
        retention = get_retention_limits()
        deleted_executions = 0
        deleted_artifact_dirs = 0

        async with async_session_maker() as db:
            from app.models.script import Script

            script_result = await db.execute(select(Script.id))
            script_ids = [row[0] for row in script_result.all()]

            for script_id in script_ids:
                for status, keep_count in retention.items():
                    # IDs of the N most recent executions to keep
                    keep_result = await db.execute(
                        select(Execution.id)
                        .where(
                            Execution.script_id == script_id,
                            Execution.status == status,
                        )
                        .order_by(Execution.started_at.desc())
                        .limit(keep_count)
                    )
                    keep_ids = {row[0] for row in keep_result.all()}

                    # All execution IDs for this script + status
                    all_result = await db.execute(
                        select(Execution.id).where(
                            Execution.script_id == script_id,
                            Execution.status == status,
                        )
                    )
                    all_ids = {row[0] for row in all_result.all()}

                    to_delete = all_ids - keep_ids
                    if not to_delete:
                        continue

                    # Clean up artifact directories first
                    for exec_id in to_delete:
                        artifact_dir = cfg.artifacts_dir / str(exec_id)
                        if artifact_dir.exists():
                            try:
                                shutil.rmtree(artifact_dir)
                                deleted_artifact_dirs += 1
                            except Exception as exc:
                                logger.warning(
                                    "Failed to remove artifact dir %s: %s", artifact_dir, exc
                                )

                    await db.execute(delete(Execution).where(Execution.id.in_(to_delete)))
                    deleted_executions += len(to_delete)

            await db.commit()

        logger.info(
            "Status-aware cleanup complete: %d executions deleted, %d artifact dirs removed",
            deleted_executions,
            deleted_artifact_dirs,
        )
        if deleted_executions >= MASS_DELETE_WARNING_THRESHOLD:
            logger.warning(
                "Status-aware cleanup deleted %d executions in a single run "
                "(>= %d) — check retention limits if this is unexpected",
                deleted_executions,
                MASS_DELETE_WARNING_THRESHOLD,
            )
        return {
            "deleted_executions": deleted_executions,
            "deleted_artifact_dirs": deleted_artifact_dirs,
            "retention": retention,
        }

    async def cleanup_older_than_days(self, days: int) -> dict:
        """
        Delete all non-running executions older than `days` days.

        Also removes their artifact directories from the filesystem.
        """
        cfg = get_settings()
        cutoff = datetime.now(UTC) - timedelta(days=days)

        async with async_session_maker() as db:
            id_result = await db.execute(
                select(Execution.id).where(
                    Execution.started_at < cutoff,
                    Execution.status != ExecutionStatus.RUNNING.value,
                )
            )
            to_delete = [row[0] for row in id_result.all()]

            if not to_delete:
                return {"deleted_executions": 0, "deleted_artifact_dirs": 0}

            deleted_artifact_dirs = 0
            for exec_id in to_delete:
                artifact_dir = cfg.artifacts_dir / str(exec_id)
                if artifact_dir.exists():
                    try:
                        shutil.rmtree(artifact_dir)
                        deleted_artifact_dirs += 1
                    except Exception as exc:
                        logger.warning("Failed to remove artifact dir %s: %s", artifact_dir, exc)

            await db.execute(delete(Execution).where(Execution.id.in_(to_delete)))
            await db.commit()

        logger.info(
            "Age-based cleanup: %d executions older than %d days deleted",
            len(to_delete),
            days,
        )
        return {
            "deleted_executions": len(to_delete),
            "deleted_artifact_dirs": deleted_artifact_dirs,
        }

    async def get_execution_stats(self) -> dict:
        """Return execution counts and oldest record date for the Settings page."""
        async with async_session_maker() as db:
            total_result = await db.execute(select(func.count(Execution.id)))
            total = total_result.scalar() or 0

            by_status: dict[str, int] = {}
            for status in (
                ExecutionStatus.SUCCESS.value,
                ExecutionStatus.FAILED.value,
                ExecutionStatus.SKIPPED.value,
                ExecutionStatus.CANCELLED.value,
                ExecutionStatus.RUNNING.value,
            ):
                cnt_result = await db.execute(
                    select(func.count(Execution.id)).where(Execution.status == status)
                )
                by_status[status] = cnt_result.scalar() or 0

            oldest_result = await db.execute(
                select(Execution.started_at)
                .where(Execution.status != ExecutionStatus.RUNNING.value)
                .order_by(Execution.started_at.asc())
                .limit(1)
            )
            oldest = oldest_result.scalar()

        return {
            "total": total,
            "by_status": by_status,
            "oldest_at": oldest.isoformat() if oldest else None,
        }


cleanup_service = CleanupService()
