"""Git synchronization service."""

import asyncio
import logging
from pathlib import Path

import yaml
from git import Repo
from git.exc import GitError
from sqlalchemy import select

from app.config import get_settings
from app.database import async_session_maker
from app.models.script import Script

logger = logging.getLogger(__name__)
settings = get_settings()


class GitSyncService:
    """Service for synchronizing scripts from a Git repository."""

    def __init__(self) -> None:
        self.enabled = settings.git_enabled
        self.repo_url = settings.git_repo_url
        self.branch = settings.git_branch
        self.sync_interval = settings.git_sync_interval
        self.scripts_subdir = settings.git_scripts_subdir
        
        self._repo: Repo | None = None
        self._sync_task: asyncio.Task | None = None
        self._repo_path = settings.data_dir / "git_repo"

    async def start(self) -> None:
        """Start the git sync service."""
        if not self.enabled:
            logger.info("Git sync is disabled")
            return

        if not self.repo_url:
            logger.warning("Git repo URL not configured")
            return

        # Initial sync
        await self.sync()

        # Start periodic sync
        self._sync_task = asyncio.create_task(self._periodic_sync())
        logger.info(f"Git sync started, interval: {self.sync_interval}s")

    async def stop(self) -> None:
        """Stop the git sync service."""
        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
        logger.info("Git sync stopped")

    async def _periodic_sync(self) -> None:
        """Periodically sync from git."""
        while True:
            await asyncio.sleep(self.sync_interval)
            try:
                await self.sync()
            except Exception as e:
                logger.exception(f"Git sync failed: {e}")

    async def sync(self) -> tuple[bool, str]:
        """
        Sync scripts from the git repository.
        
        Returns:
            Tuple of (success, message)
        """
        if not self.enabled or not self.repo_url:
            return False, "Git sync is not configured"

        try:
            # Clone or pull
            if self._repo_path.exists():
                success, msg = await self._pull()
            else:
                success, msg = await self._clone()

            if not success:
                return False, msg

            # Scan for scripts
            await self._scan_and_update_scripts()

            return True, "Sync completed successfully"

        except Exception as e:
            logger.exception("Git sync error")
            return False, str(e)

    async def _clone(self) -> tuple[bool, str]:
        """Clone the repository."""
        try:
            logger.info(f"Cloning repository: {self.repo_url}")
            
            # Run git clone in a thread pool
            loop = asyncio.get_event_loop()
            self._repo = await loop.run_in_executor(
                None,
                lambda: Repo.clone_from(
                    self.repo_url,
                    self._repo_path,
                    branch=self.branch,
                ),
            )
            
            return True, "Repository cloned"

        except GitError as e:
            return False, f"Clone failed: {e}"

    async def _pull(self) -> tuple[bool, str]:
        """Pull latest changes."""
        try:
            logger.info("Pulling latest changes")
            
            if not self._repo:
                self._repo = Repo(self._repo_path)

            loop = asyncio.get_event_loop()
            
            # Fetch and reset to origin/branch
            await loop.run_in_executor(
                None,
                lambda: self._repo.remotes.origin.fetch(),
            )
            await loop.run_in_executor(
                None,
                lambda: self._repo.head.reset(
                    f"origin/{self.branch}",
                    index=True,
                    working_tree=True,
                ),
            )

            return True, "Repository updated"

        except GitError as e:
            return False, f"Pull failed: {e}"

    async def _scan_and_update_scripts(self) -> None:
        """Scan the repository for scripts and update the database."""
        scripts_path = self._repo_path
        if self.scripts_subdir:
            scripts_path = scripts_path / self.scripts_subdir

        if not scripts_path.exists():
            logger.warning(f"Scripts directory not found: {scripts_path}")
            return

        current_commit = self._repo.head.commit.hexsha if self._repo else None

        async with async_session_maker() as db:
            # Scan for cronator.yaml files
            for config_path in scripts_path.rglob("cronator.yaml"):
                await self._process_script_config(db, config_path, current_commit)

            # Also scan for cronator.yml
            for config_path in scripts_path.rglob("cronator.yml"):
                await self._process_script_config(db, config_path, current_commit)

            await db.commit()

    async def _process_script_config(
        self,
        db,
        config_path: Path,
        commit: str | None,
    ) -> None:
        """Process a single script configuration file."""
        try:
            with open(config_path) as f:
                config = yaml.safe_load(f)

            if not config:
                return

            script_dir = config_path.parent
            script_name = config.get("name") or script_dir.name
            script_file = config.get("script", "script.py")
            script_path = script_dir / script_file

            if not script_path.exists():
                logger.warning(f"Script file not found: {script_path}")
                return

            # Check if script exists in database
            result = await db.execute(
                select(Script).where(Script.name == script_name)
            )
            script = result.scalar_one_or_none()

            # Read script content
            with open(script_path) as f:
                content = f.read()

            # Read dependencies
            deps_file = script_dir / "requirements.txt"
            dependencies = ""
            if deps_file.exists():
                with open(deps_file) as f:
                    dependencies = f.read()
            elif config.get("dependencies"):
                dependencies = "\n".join(config["dependencies"])

            if script:
                # Update existing script
                script.content = content
                script.cron_expression = config.get("schedule", script.cron_expression)
                script.python_version = config.get("python", script.python_version)
                script.dependencies = dependencies
                script.enabled = config.get("enabled", script.enabled)
                script.timeout = config.get("timeout", script.timeout)
                script.description = config.get("description", script.description)
                script.git_commit = commit
                
                logger.info(f"Updated script from git: {script_name}")
            else:
                # Create new script
                new_script = Script(
                    name=script_name,
                    description=config.get("description", ""),
                    path=str(script_path),
                    content=content,
                    cron_expression=config.get("schedule", "0 * * * *"),
                    python_version=config.get("python", "3.11"),
                    dependencies=dependencies,
                    enabled=config.get("enabled", True),
                    timeout=config.get("timeout", 3600),
                    alert_on_failure=config.get("alert_on_failure", True),
                    git_commit=commit,
                )
                db.add(new_script)
                
                logger.info(f"Added new script from git: {script_name}")

        except Exception as e:
            logger.exception(f"Error processing script config {config_path}: {e}")

    def get_current_commit(self) -> str | None:
        """Get the current commit hash."""
        if self._repo:
            return self._repo.head.commit.hexsha
        return None

    def get_status(self) -> dict:
        """Get git sync status."""
        return {
            "enabled": self.enabled,
            "repo_url": self.repo_url,
            "branch": self.branch,
            "current_commit": self.get_current_commit(),
            "sync_interval": self.sync_interval,
            "repo_cloned": self._repo_path.exists(),
        }


# Global instance
git_sync_service = GitSyncService()
