"""Scheduler service using APScheduler."""

import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.database import async_session_maker
from app.models.script import Script

logger = logging.getLogger(__name__)


def parse_cron_expression(cron_expression: str) -> CronTrigger | None:
    """Parse a five-field cron expression into an APScheduler trigger.

    Module-level on purpose: the missed-run detector recomputes expected fire
    times from the same expressions the scheduler dispatches, and the two
    must never disagree about what an expression means.
    """
    parts = cron_expression.strip().split()
    if len(parts) != 5:
        return None

    minute, hour, day, month, day_of_week = parts
    try:
        # timezone="UTC" is explicit on purpose: CronTrigger otherwise
        # resolves the *host's* local timezone, and the documented contract
        # ("evaluated in UTC") must hold on a dev Windows box too, not just
        # in the container where TZ=UTC makes the two coincide.
        return CronTrigger(
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
            timezone="UTC",
        )
    except Exception as e:
        logger.error(f"Error parsing cron expression '{cron_expression}': {e}")
        return None


class SchedulerService:
    """Service for managing scheduled script execution."""

    def __init__(self) -> None:
        self.scheduler = AsyncIOScheduler(timezone="UTC")

    async def start(self) -> None:
        """Start the scheduler and load all enabled scripts."""
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("Scheduler started")
            await self.reload_all_jobs()

    async def stop(self) -> None:
        """Stop the scheduler."""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")

    async def reload_all_jobs(self) -> None:
        """Reload all jobs from database."""
        # Remove all existing jobs
        self.scheduler.remove_all_jobs()

        async with async_session_maker() as db:
            result = await db.execute(select(Script).where(Script.enabled))
            scripts = result.scalars().all()

            for script in scripts:
                await self.add_job(script)

        # Re-register internal system jobs (removed by remove_all_jobs above)
        self._register_internal_jobs()

        logger.info(f"Loaded {len(scripts)} scheduled jobs")

    async def add_job(self, script: Script) -> bool:
        """Add a job for a script."""
        try:
            if not script.enabled:
                return False

            job_id = f"script_{script.id}"

            # Remove existing job if present
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)

            # Parse cron expression
            trigger = self._parse_cron(script.cron_expression)
            if not trigger:
                logger.error(
                    f"Invalid cron expression for script {script.name}: {script.cron_expression}"
                )
                return False

            # Add job
            self.scheduler.add_job(
                self._execute_script,
                trigger=trigger,
                id=job_id,
                name=script.name,
                args=[script.id],
                replace_existing=True,
                misfire_grace_time=script.misfire_grace_time,
            )

            logger.info(
                f"Added job for script {script.name} with schedule: {script.cron_expression}"
            )
            return True

        except Exception:
            logger.exception(f"Error adding job for script {script.name}")
            return False

    async def remove_job(self, script_id: int) -> bool:
        """Remove a job for a script."""
        try:
            job_id = f"script_{script_id}"
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
                logger.info(f"Removed job for script_id={script_id}")
            return True
        except Exception:
            logger.exception(f"Error removing job for script_id={script_id}")
            return False

    async def update_job(self, script: Script) -> bool:
        """Update a job for a script."""
        await self.remove_job(script.id)
        if script.enabled:
            return await self.add_job(script)
        return True

    def _parse_cron(self, cron_expression: str) -> CronTrigger | None:
        """Parse a cron expression into a trigger."""
        return parse_cron_expression(cron_expression)

    def _register_internal_jobs(self) -> None:
        """Register built-in system jobs (cleanup, etc.)."""
        self.scheduler.add_job(
            self._run_cleanup,
            trigger=CronTrigger(hour=3, minute=0, timezone="UTC"),
            id="internal_cleanup",
            name="Execution History Cleanup",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self._run_auto_backup,
            trigger=CronTrigger(hour=2, minute=0, timezone="UTC"),
            id="internal_auto_backup",
            name="Automated Database Backup",
            replace_existing=True,
        )
        # A cron moment lost to downtime leaves no row by itself; the sweep
        # recomputes expected fires from the expressions and records the
        # gap. Frequent on purpose: a missed schedule is only actionable
        # while the operator still remembers what happened around it.
        self.scheduler.add_job(
            self._run_missed_detection,
            trigger=IntervalTrigger(minutes=5, timezone="UTC"),
            id="internal_missed_runs",
            name="Missed Schedule Detection",
            replace_existing=True,
        )
        # The startup cleanup covers rows stranded by a restart; this one
        # covers the same anomaly while the process stays up.
        self.scheduler.add_job(
            self._run_stale_sweep,
            trigger=IntervalTrigger(minutes=15, timezone="UTC"),
            id="internal_stale_execution_sweep",
            name="Stale RUNNING Execution Sweep",
            replace_existing=True,
        )

    async def _run_cleanup(self) -> None:
        """Run the daily status-aware execution history cleanup."""
        from app.services.cleanup_service import cleanup_service

        try:
            await cleanup_service.cleanup_by_status()
        except Exception:
            logger.exception("Error during scheduled execution history cleanup")

        # Sessions outlive their owners without this: expired rows are
        # harmless (validate_session re-checks the date) but pile up in
        # the table until someone restarts the app.
        from app.services.auth_session import purge_expired

        try:
            purged = await purge_expired()
            if purged:
                logger.info("Purged %d expired login sessions", purged)
        except Exception:
            logger.exception("Error purging expired login sessions")

    async def _run_auto_backup(self) -> None:
        """Run the daily automated database backup, if enabled (P0)."""
        from app.services.backup_service import backup_service
        from app.services.settings_service import settings_service

        try:
            enabled = await settings_service.get("auto_backup_enabled", False)
            if not enabled:
                return
            path = await backup_service.create_backup()
            logger.info(f"Automated backup created: {path}")
        except Exception:
            logger.exception("Error during scheduled automated backup")

    async def _run_missed_detection(self) -> None:
        """Record executions for cron moments that fired nothing."""
        from app.services.missed_runs import detect_missed_runs

        try:
            await detect_missed_runs()
        except Exception:
            # A detector that takes the scheduler down would be worse than
            # the gap it is trying to measure.
            logger.exception("Error during missed-run detection")

    async def _run_stale_sweep(self) -> None:
        """Fail RUNNING rows whose live process is long gone."""
        from app.services.executor import executor_service

        try:
            marked = await executor_service.sweep_stale_running_executions()
            if marked:
                logger.warning("Stale-execution sweep marked %d row(s) failed", marked)
        except Exception:
            logger.exception("Error during stale execution sweep")

    async def _execute_script(self, script_id: int) -> None:
        """Execute a script (called by scheduler)."""
        from app.services.executor import executor_service

        try:
            await executor_service.execute_script(script_id, triggered_by="scheduler")
        except Exception:
            logger.exception(f"Error executing script {script_id} from scheduler")

    def get_next_run_time(self, script_id: int) -> datetime | None:
        """Get the next run time for a script."""
        job_id = f"script_{script_id}"
        job = self.scheduler.get_job(job_id)
        if job:
            # Support both APScheduler 3.x and 4.x
            return getattr(job, "next_run_time", None) or getattr(job, "next_fire_time", None)
        return None

    def get_all_jobs_info(self) -> list[dict]:
        """Get info about all scheduled jobs."""
        jobs = []
        for job in self.scheduler.get_jobs():
            # Support both APScheduler 3.x and 4.x
            next_time = getattr(job, "next_run_time", None) or getattr(job, "next_fire_time", None)
            jobs.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run_time": next_time,
                    "trigger": str(job.trigger),
                }
            )
        return jobs


# Global instance
scheduler_service = SchedulerService()
