"""Scheduler service using APScheduler."""

import logging
from collections.abc import Callable
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.database import async_session_maker
from app.models.script import Script

logger = logging.getLogger(__name__)


class SchedulerService:
    """Service for managing scheduled script execution."""

    def __init__(self) -> None:
        self.scheduler = AsyncIOScheduler(timezone="UTC")
        self._execute_callback: Callable[[int], None] | None = None

    def set_execute_callback(self, callback: Callable[[int], None]) -> None:
        """Set the callback function for executing scripts."""
        self._execute_callback = callback

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
            result = await db.execute(
                select(Script).where(Script.enabled)
            )
            scripts = result.scalars().all()

            for script in scripts:
                await self.add_job(script)

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
                    f"Invalid cron expression for script {script.name}: "
                    f"{script.cron_expression}"
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
                f"Added job for script {script.name} with schedule: "
                f"{script.cron_expression}"
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
        try:
            parts = cron_expression.strip().split()
            if len(parts) != 5:
                return None
            
            minute, hour, day, month, day_of_week = parts
            
            return CronTrigger(
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=day_of_week,
            )
        except Exception as e:
            logger.error(f"Error parsing cron expression '{cron_expression}': {e}")
            return None

    async def _execute_script(self, script_id: int) -> None:
        """Execute a script (called by scheduler)."""
        if self._execute_callback:
            from app.services.executor import executor_service
            await executor_service.execute_script(script_id, triggered_by="scheduler")
        else:
            logger.warning(f"No execute callback set, cannot execute script {script_id}")

    def get_next_run_time(self, script_id: int) -> datetime | None:
        """Get the next run time for a script."""
        job_id = f"script_{script_id}"
        job = self.scheduler.get_job(job_id)
        if job:
            return job.next_run_time
        return None

    def get_all_jobs_info(self) -> list[dict]:
        """Get info about all scheduled jobs."""
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run_time": job.next_run_time,
                "trigger": str(job.trigger),
            })
        return jobs


# Global instance
scheduler_service = SchedulerService()
