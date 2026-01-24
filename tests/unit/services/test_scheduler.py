"""Unit tests for Scheduler service."""

import pytest

from app.models.script import Script
from app.services.scheduler import SchedulerService


class TestSchedulerService:
    """Tests for SchedulerService."""

    def test_parse_cron_valid_expression(self):
        """Test parsing valid cron expressions."""
        service = SchedulerService()

        # Standard cron expressions
        valid_expressions = [
            "* * * * *",  # every minute
            "0 * * * *",  # every hour
            "0 0 * * *",  # every day at midnight
            "*/5 * * * *",  # every 5 minutes
            "0 12 * * 1-5",  # noon on weekdays
            "30 4 1 * *",  # 4:30 AM on 1st of month
        ]

        for expr in valid_expressions:
            trigger = service._parse_cron(expr)
            assert trigger is not None, f"Expression '{expr}' should be valid"

    def test_parse_cron_invalid_expression(self):
        """Test parsing invalid cron expressions."""
        service = SchedulerService()

        invalid_expressions = [
            "",  # empty
            "* * *",  # too few fields (3)
            "* * * *",  # too few fields (4)
            "* * * * * *",  # too many fields (6)
            "invalid",  # not a cron
        ]

        for expr in invalid_expressions:
            trigger = service._parse_cron(expr)
            assert trigger is None, f"Expression '{expr}' should be invalid"

    def test_init_creates_scheduler(self):
        """Test that init creates APScheduler instance."""
        service = SchedulerService()
        assert service.scheduler is not None
        # Scheduler timezone is set to UTC
        assert str(service.scheduler.timezone) == "UTC"

    @pytest.mark.asyncio
    async def test_add_job_disabled_script(self, db_session):
        """Test that disabled scripts are not added."""
        service = SchedulerService()

        script = Script(
            id=1,
            name="disabled_script",
            path="/path/to/script.py",
            cron_expression="* * * * *",
            enabled=False,
        )

        result = await service.add_job(script)
        assert result is False

    @pytest.mark.asyncio
    async def test_add_job_enabled_script(self):
        """Test adding job for enabled script."""
        service = SchedulerService()
        service.scheduler.start()

        try:
            script = Script(
                id=99,
                name="test_job_script",
                path="/path/to/script.py",
                cron_expression="0 * * * *",
                enabled=True,
                misfire_grace_time=60,
            )

            result = await service.add_job(script)
            assert result is True

            # Verify job was added
            job = service.scheduler.get_job("script_99")
            assert job is not None
            assert job.name == "test_job_script"
        finally:
            service.scheduler.shutdown(wait=False)

    @pytest.mark.asyncio
    async def test_remove_job(self):
        """Test removing a job."""
        service = SchedulerService()
        service.scheduler.start()

        try:
            # First add a job
            script = Script(
                id=100,
                name="remove_test",
                path="/path/to/script.py",
                cron_expression="0 * * * *",
                enabled=True,
            )
            await service.add_job(script)

            # Verify it exists
            assert service.scheduler.get_job("script_100") is not None

            # Remove it
            result = await service.remove_job(100)
            assert result is True

            # Verify it's gone
            assert service.scheduler.get_job("script_100") is None
        finally:
            service.scheduler.shutdown(wait=False)

    @pytest.mark.asyncio
    async def test_update_job_enables_disabled(self):
        """Test updating a disabled script enables the job."""
        service = SchedulerService()
        service.scheduler.start()

        try:
            script = Script(
                id=101,
                name="update_test",
                path="/path/to/script.py",
                cron_expression="0 * * * *",
                enabled=True,
            )

            result = await service.update_job(script)
            assert result is True
            assert service.scheduler.get_job("script_101") is not None
        finally:
            service.scheduler.shutdown(wait=False)

    @pytest.mark.asyncio
    async def test_update_job_disables_enabled(self):
        """Test updating an enabled script to disabled removes the job."""
        service = SchedulerService()
        service.scheduler.start()

        try:
            # First add enabled
            script = Script(
                id=102,
                name="disable_test",
                path="/path/to/script.py",
                cron_expression="0 * * * *",
                enabled=True,
            )
            await service.add_job(script)

            # Disable and update
            script.enabled = False
            await service.update_job(script)

            # Job should be removed
            assert service.scheduler.get_job("script_102") is None
        finally:
            service.scheduler.shutdown(wait=False)

    def test_get_next_run_time_no_job(self):
        """Test getting next run time for non-existent job."""
        service = SchedulerService()
        result = service.get_next_run_time(999)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_all_jobs_info_empty(self):
        """Test getting all jobs info when empty."""
        service = SchedulerService()
        service.scheduler.start()

        try:
            jobs = service.get_all_jobs_info()
            assert jobs == []
        finally:
            service.scheduler.shutdown(wait=False)

    @pytest.mark.asyncio
    async def test_get_all_jobs_info_with_jobs(self):
        """Test getting all jobs info with jobs."""
        service = SchedulerService()
        service.scheduler.start()

        try:
            script = Script(
                id=103,
                name="info_test",
                path="/path/to/script.py",
                cron_expression="0 12 * * *",
                enabled=True,
            )
            await service.add_job(script)

            jobs = service.get_all_jobs_info()
            assert len(jobs) == 1
            assert jobs[0]["id"] == "script_103"
            assert jobs[0]["name"] == "info_test"
            assert "next_run_time" in jobs[0]
        finally:
            service.scheduler.shutdown(wait=False)
