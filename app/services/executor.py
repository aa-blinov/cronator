"""Script execution service."""

import asyncio
import json
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import async_session_maker
from app.models.artifact import Artifact
from app.models.execution import Execution, ExecutionStatus
from app.models.script import Script
from app.services.environment import environment_service

logger = logging.getLogger(__name__)
settings = get_settings()


class ExecutorService:
    """Service for executing Python scripts."""

    def __init__(self) -> None:
        self.running_processes: dict[int, asyncio.subprocess.Process] = {}
        self.output_queues: dict[int, asyncio.Queue] = {}
        self._script_locks: dict[int, asyncio.Lock] = {}
        self._running_scripts: set[int] = set()

    def _get_script_lock(self, script_id: int) -> asyncio.Lock:
        """Get or create a lock for a specific script."""
        if script_id not in self._script_locks:
            self._script_locks[script_id] = asyncio.Lock()
        return self._script_locks[script_id]

    async def execute_script(
        self,
        script_id: int,
        triggered_by: str = "scheduler",
        is_test: bool = False,
    ) -> int:
        """
        Execute a script and return the execution ID.

        Args:
            script_id: ID of the script to execute
            triggered_by: Who triggered the execution (scheduler, manual, api, test)
            is_test: Whether this is a test execution

        Returns:
            Execution ID
        """
        # Acquire lock to prevent race condition
        lock = self._get_script_lock(script_id)
        async with lock:
            # Check if script is already running (prevent concurrent execution of same script)
            if script_id in self._running_scripts:
                logger.warning(f"Script {script_id} is already running, skipping execution")
                raise ValueError(f"Script {script_id} is already running")

            # Mark script as running immediately while holding lock
            self._running_scripts.add(script_id)

        async with async_session_maker() as db:
            # Get script
            result = await db.execute(select(Script).where(Script.id == script_id))
            script = result.scalar_one_or_none()

            if not script:
                raise ValueError(f"Script with ID {script_id} not found")

            # Create execution record
            execution = Execution(
                script_id=script_id,
                status=ExecutionStatus.RUNNING.value,
                triggered_by=triggered_by,
                is_test=is_test,
                started_at=datetime.now(UTC),
            )
            db.add(execution)
            await db.commit()
            await db.refresh(execution)

            execution_id = execution.id

        # Run execution in background
        asyncio.create_task(self._run_script(script_id, execution_id))

        return execution_id

    def is_script_running(self, script_id: int) -> bool:
        """Check if a script is currently running."""
        return script_id in self._running_scripts

    async def _run_script(self, script_id: int, execution_id: int) -> None:
        """Actually run the script (called in background)."""
        async with async_session_maker() as db:
            try:
                # Get script and execution
                result = await db.execute(select(Script).where(Script.id == script_id))
                script = result.scalar_one_or_none()

                result = await db.execute(select(Execution).where(Execution.id == execution_id))
                execution = result.scalar_one_or_none()

                if not script or not execution:
                    logger.error(f"Script or execution not found: {script_id}, {execution_id}")
                    return

                # Create output queue early so SSE stream can receive 'done' message
                # even if execution fails
                output_queue = asyncio.Queue()
                self.output_queues[execution_id] = output_queue

                # Determine script path
                script_path = self._get_script_path(script)
                if not script_path.exists():
                    await self._finish_execution(
                        db,
                        execution,
                        status=ExecutionStatus.FAILED,
                        error_message=f"Script file not found: {script_path}",
                    )
                    # Signal end of stream
                    await asyncio.sleep(0.1)  # Small delay to ensure DB commit is visible
                    await output_queue.put(("done", None))
                    return

                # Ensure environment exists
                if not await environment_service.env_exists(script.name):
                    logger.info(f"Creating environment for {script.name}")
                    success, msg = await environment_service.setup_environment(
                        script.name,
                        script.python_version,
                        script.dependencies,
                    )
                    if not success:
                        await self._finish_execution(
                            db,
                            execution,
                            status=ExecutionStatus.FAILED,
                            error_message=f"Failed to setup environment: {msg}",
                        )
                        # Signal end of stream
                        await asyncio.sleep(0.1)  # Small delay to ensure DB commit is visible
                        await output_queue.put(("done", None))
                        return

                # Get Python path
                python_path = environment_service.get_python_path(script.name)
                if not python_path.exists():
                    await self._finish_execution(
                        db,
                        execution,
                        status=ExecutionStatus.FAILED,
                        error_message=f"Python not found at {python_path}",
                    )
                    # Signal end of stream
                    await asyncio.sleep(0.1)  # Small delay to ensure DB commit is visible
                    await output_queue.put(("done", None))
                    return

                # Prepare environment variables
                env = os.environ.copy()
                
                # Ensure Oracle Client environment variables are set
                # These are critical for cx_Oracle to find the Oracle Instant Client libraries
                oracle_lib_path = "/usr/lib/instantclient"
                if "LD_LIBRARY_PATH" not in env:
                    env["LD_LIBRARY_PATH"] = oracle_lib_path
                elif oracle_lib_path not in env["LD_LIBRARY_PATH"]:
                    env["LD_LIBRARY_PATH"] = f"{oracle_lib_path}:{env['LD_LIBRARY_PATH']}"
                
                env.setdefault("ORACLE_HOME", oracle_lib_path)
                env.setdefault("ORACLE_BASE", oracle_lib_path)
                env.setdefault("TNS_ADMIN", oracle_lib_path)
                
                if script.environment_vars:
                    try:
                        extra_env = json.loads(script.environment_vars)
                        env.update(extra_env)
                    except json.JSONDecodeError:
                        # Try line-by-line format: KEY=VALUE
                        for line in script.environment_vars.split("\n"):
                            if "=" in line:
                                key, value = line.split("=", 1)
                                env[key.strip()] = value.strip()

                # Add cronator-specific env vars
                env["CRONATOR_SCRIPT_ID"] = str(script_id)
                env["CRONATOR_EXECUTION_ID"] = str(execution_id)
                env["CRONATOR_SCRIPT_NAME"] = script.name

                # Add cronator_lib to PYTHONPATH so scripts can import it
                # even if not installed in venv
                cronator_lib_parent = str(settings.base_dir)
                if "PYTHONPATH" in env:
                    env["PYTHONPATH"] = f"{cronator_lib_parent}{os.pathsep}{env['PYTHONPATH']}"
                else:
                    env["PYTHONPATH"] = cronator_lib_parent

                # Create artifacts directory for this execution
                execution_artifacts_dir = settings.artifacts_dir / str(execution_id)
                try:
                    execution_artifacts_dir.mkdir(parents=True, exist_ok=True)
                except (PermissionError, OSError) as e:
                    logger.warning(
                        f"Could not create artifacts directory {execution_artifacts_dir}: {e}. "
                        "Artifacts will not be saved for this execution."
                    )
                    # Set to a temp directory as fallback, or None if we can't create anything
                    execution_artifacts_dir = None
                env["CRONATOR_ARTIFACTS_DIR"] = (
                    str(execution_artifacts_dir) if execution_artifacts_dir else ""
                )

                # Determine working directory
                if script.working_directory:
                    cwd = Path(script.working_directory)
                else:
                    cwd = script_path.parent

                # Run the script
                logger.info(f"Executing script {script.name} (execution_id={execution_id})")
                logger.info(f"Python path: {python_path} (exists: {python_path.exists()})")
                logger.info(f"Script path: {script_path} (exists: {script_path.exists()})")
                logger.info(f"Working directory: {cwd}")

                start_time = datetime.now(UTC)

                try:
                    process = await asyncio.create_subprocess_exec(
                        str(python_path),
                        "-u",  # Unbuffered output for real-time streaming
                        str(script_path),
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=str(cwd),
                        env=env,
                    )

                    self.running_processes[execution_id] = process

                    # Output queue already created above

                    # Collect output and stream to queue
                    stdout_lines = []
                    stderr_lines = []
                    artifacts_metadata = []  # Track artifacts created during execution

                    async def read_stream(stream, is_stderr=False):
                        """Read stream line by line and add to queue."""
                        while True:
                            line = await stream.readline()
                            if not line:
                                break
                            decoded = line.decode("utf-8", errors="replace")
                            if is_stderr:
                                stderr_lines.append(decoded)
                            else:
                                stdout_lines.append(decoded)
                                # Parse for artifact markers
                                if "ARTIFACT_SAVED:" in decoded:
                                    try:
                                        # Format: ARTIFACT_SAVED:{filename}:{size}:{original_name}
                                        # First try to parse as JSON (from CronatorFormatter)
                                        message = decoded.strip()
                                        if message.startswith("{"):
                                            try:
                                                log_entry = json.loads(message)
                                                message = log_entry.get("message", message)
                                            except json.JSONDecodeError:
                                                pass

                                        # Now extract artifact info from message
                                        match = re.search(
                                            r"ARTIFACT_SAVED:([^:]+):(\d+):([^\"}\n]+)", message
                                        )
                                        if match:
                                            filename = match.group(1).strip()
                                            size_bytes = int(match.group(2))
                                            original_name = match.group(3).strip()
                                            artifacts_metadata.append(
                                                {
                                                    "filename": filename,
                                                    "size_bytes": size_bytes,
                                                    "original_filename": original_name,
                                                }
                                            )
                                            logger.info(
                                                f"Detected artifact: {original_name} "
                                                f"(saved as {filename}, {size_bytes} bytes)"
                                            )
                                    except Exception as e:
                                        logger.warning(f"Failed to parse artifact metadata: {e}")
                            # Add to queue for streaming
                            await output_queue.put(("stderr" if is_stderr else "stdout", decoded))

                    # Read both streams concurrently
                    await asyncio.gather(
                        read_stream(process.stdout, False),
                        read_stream(process.stderr, True),
                    )

                    try:
                        exit_code = await asyncio.wait_for(
                            process.wait(),
                            timeout=script.timeout,
                        )

                        stdout_text = "".join(stdout_lines)
                        stderr_text = "".join(stderr_lines)

                        # Truncate if too large
                        if len(stdout_text) > settings.max_log_size:
                            stdout_text = stdout_text[: settings.max_log_size] + "\n... (truncated)"
                        if len(stderr_text) > settings.max_log_size:
                            stderr_text = stderr_text[: settings.max_log_size] + "\n... (truncated)"

                        await db.refresh(execution)
                        if execution.status == ExecutionStatus.CANCELLED.value:
                            status = ExecutionStatus.CANCELLED
                        elif exit_code == 0:
                            status = ExecutionStatus.SUCCESS
                        else:
                            status = ExecutionStatus.FAILED

                        await self._finish_execution(
                            db,
                            execution,
                            status=status,
                            exit_code=exit_code,
                            stdout=stdout_text,
                            stderr=stderr_text,
                            start_time=start_time,
                            artifacts_metadata=artifacts_metadata,
                        )

                    except TimeoutError:
                        process.kill()
                        await process.wait()
                        await self._finish_execution(
                            db,
                            execution,
                            status=ExecutionStatus.TIMEOUT,
                            error_message=f"Script timed out after {script.timeout} seconds",
                            start_time=start_time,
                        )

                finally:
                    # Cleanup
                    self.running_processes.pop(execution_id, None)
                    # Signal end of stream
                    # Note: Don't delete the queue here - let the SSE handler clean it up
                    # after consuming the 'done' message to prevent race condition
                    if execution_id in self.output_queues:
                        try:
                            # Small delay to ensure DB commit is visible to other sessions
                            await asyncio.sleep(0.1)
                            await self.output_queues[execution_id].put(("done", None))
                        except Exception:
                            pass

            except Exception as e:
                logger.exception(f"Error executing script {script_id}")
                # Create queue if it doesn't exist (for early errors)
                if execution_id not in self.output_queues:
                    output_queue = asyncio.Queue()
                    self.output_queues[execution_id] = output_queue
                else:
                    output_queue = self.output_queues[execution_id]

                # Try to get execution if not already available
                if "execution" not in locals():
                    result = await db.execute(select(Execution).where(Execution.id == execution_id))
                    execution = result.scalar_one_or_none()

                if execution:
                    await self._finish_execution(
                        db,
                        execution,
                        status=ExecutionStatus.FAILED,
                        error_message=str(e),
                    )
                    # Signal end of stream
                    try:
                        await asyncio.sleep(0.1)  # Small delay to ensure DB commit is visible
                        await output_queue.put(("done", None))
                    except Exception:
                        pass
                else:
                    # If we can't get execution, just signal done
                    try:
                        await output_queue.put(("done", None))
                    except Exception:
                        pass
            finally:
                # Always remove script from running set
                self._running_scripts.discard(script_id)

    def _get_script_path(self, script: Script) -> Path:
        """Get the path to the script file."""
        if script.path:
            path = Path(script.path)
            if path.is_absolute():
                return path
            return settings.scripts_dir / path

        # For UI-created scripts, use generated path
        return settings.scripts_dir / script.name / "script.py"

    async def _finish_execution(
        self,
        db: AsyncSession,
        execution: Execution,
        status: ExecutionStatus,
        exit_code: int | None = None,
        stdout: str = "",
        stderr: str = "",
        error_message: str | None = None,
        start_time: datetime | None = None,
        artifacts_metadata: list[dict] | None = None,
    ) -> None:
        """Update execution with final status."""
        # Refresh execution to get latest status (might have been cancelled)
        await db.refresh(execution)
        
        # Don't overwrite CANCELLED status - it was set by user action
        if execution.status == ExecutionStatus.CANCELLED.value:
            logger.info(
                f"Execution {execution.id} was cancelled by user, "
                f"not updating status to {status.value}"
            )
            # Still update exit_code, stdout, stderr if not already set
            if execution.exit_code is None and exit_code is not None:
                execution.exit_code = exit_code
            if not execution.stdout and stdout:
                execution.stdout = stdout
            if not execution.stderr and stderr:
                execution.stderr = stderr
            if not execution.finished_at:
                execution.finished_at = datetime.now(UTC)
            await db.commit()
            return
        
        end_time = datetime.now(UTC)

        execution.status = status.value
        execution.finished_at = end_time
        execution.exit_code = exit_code
        execution.stdout = stdout
        execution.stderr = stderr
        execution.error_message = error_message

        if start_time:
            execution.duration_ms = int((end_time - start_time).total_seconds() * 1000)

        # Process artifacts if any were created
        if artifacts_metadata:
            try:
                artifacts_dir = settings.artifacts_dir / str(execution.id)
                total_size = 0
                created_count = 0

                for artifact_info in artifacts_metadata:
                    # Verify file exists on disk
                    artifact_path = artifacts_dir / artifact_info["filename"]
                    if artifact_path.exists():
                        # Create artifact record in database
                        artifact = Artifact(
                            execution_id=execution.id,
                            filename=artifact_info["filename"],
                            original_filename=artifact_info["original_filename"],
                            size_bytes=artifact_info["size_bytes"],
                            created_at=datetime.now(UTC),
                        )
                        db.add(artifact)
                        total_size += artifact_info["size_bytes"]
                        created_count += 1
                    else:
                        logger.warning(
                            f"Artifact file not found: {artifact_path} "
                            f"(reported by script but missing on disk)"
                        )

                # Update execution with artifact totals
                execution.artifacts_count = created_count
                execution.artifacts_size_bytes = total_size

                logger.info(
                    f"Processed {created_count} artifacts for execution {execution.id}, "
                    f"total size: {total_size} bytes"
                )

            except Exception as e:
                logger.error(f"Failed to process artifacts for execution {execution.id}: {e}")
                # Don't fail the execution, just log the error

        await db.commit()

        logger.info(
            f"Execution {execution.id} finished: status={status.value}, "
            f"exit_code={exit_code}, duration={execution.duration_ms}ms, "
            f"artifacts={execution.artifacts_count}"
        )

        # Trigger alerting if needed
        if status in (ExecutionStatus.FAILED, ExecutionStatus.TIMEOUT):
            await self._send_failure_alert(execution)
        elif status == ExecutionStatus.SUCCESS:
            await self._send_success_alert(execution)

    async def _send_failure_alert(self, execution: Execution) -> None:
        """Send alert for failed execution."""
        from app.services.alerting import alerting_service

        async with async_session_maker() as db:
            result = await db.execute(select(Script).where(Script.id == execution.script_id))
            script = result.scalar_one_or_none()

            if script and script.alert_on_failure:
                # Throttling: only send failure alert once per hour
                now = datetime.now(UTC)
                if script.last_alert_at:
                    # Ensure last_alert_at is timezone-aware
                    last_alert = script.last_alert_at
                    if last_alert.tzinfo is None:
                        last_alert = last_alert.replace(tzinfo=UTC)

                    if (now - last_alert).total_seconds() < 3600:
                        logger.info(
                            f"Throttling alert for {script.name} "
                            f"(last alert at {script.last_alert_at})"
                        )
                        return

                await alerting_service.send_failure_alert(script, execution)
                script.last_alert_at = now
                await db.commit()

    async def _send_success_alert(self, execution: Execution) -> None:
        """Send alert for successful execution."""
        from app.services.alerting import alerting_service

        async with async_session_maker() as db:
            result = await db.execute(select(Script).where(Script.id == execution.script_id))
            script = result.scalar_one_or_none()

            if script and script.alert_on_success:
                await alerting_service.send_success_alert(script, execution)
                script.last_alert_at = datetime.now(UTC)
                await db.commit()

    async def cancel_execution(self, execution_id: int) -> bool:
        """Cancel a running execution."""
        process = self.running_processes.get(execution_id)
        
        # Check execution status first
        async with async_session_maker() as db:
            result = await db.execute(select(Execution).where(Execution.id == execution_id))
            execution = result.scalar_one_or_none()
            
            if not execution:
                # Execution doesn't exist
                # Cleanup anyway in case of stale reference
                self.running_processes.pop(execution_id, None)
                return False
            
            # If execution already finished, just cleanup
            if execution.status != ExecutionStatus.RUNNING.value:
                logger.info(
                    f"Execution {execution_id} is not running (status: {execution.status}), "
                    "cleaning up stale process reference"
                )
                # Cleanup stale references
                self.running_processes.pop(execution_id, None)
                if execution.script_id:
                    self._running_scripts.discard(execution.script_id)
                return False
        
        # Execution is running, proceed with cancellation
        if process:
            try:
                process.kill()
                logger.info(f"Killed process for execution {execution_id}")
            except ProcessLookupError:
                # Process already terminated
                logger.warning(f"Process for execution {execution_id} already terminated")
            except Exception as e:
                logger.error(f"Error killing process for execution {execution_id}: {e}")

            script_id = None
            async with async_session_maker() as db:
                result = await db.execute(select(Execution).where(Execution.id == execution_id))
                execution = result.scalar_one_or_none()
                if execution:
                    script_id = execution.script_id
                    # Only update if still running (avoid race condition)
                    if execution.status == ExecutionStatus.RUNNING.value:
                        execution.status = ExecutionStatus.CANCELLED.value
                        execution.finished_at = datetime.now(UTC)
                        execution.error_message = "Cancelled by user"
                        await db.commit()
                    else:
                        logger.info(
                            f"Execution {execution_id} status changed to {execution.status} "
                            "before cancellation could be applied"
                        )

            # Signal end of stream if queue exists (for SSE)
            if execution_id in self.output_queues:
                try:
                    await asyncio.sleep(0.1)  # Small delay to ensure DB commit is visible
                    await self.output_queues[execution_id].put(("done", None))
                except Exception:
                    pass

            # Cleanup
            self.running_processes.pop(execution_id, None)
            if script_id:
                self._running_scripts.discard(script_id)

            return True
        
        # Process not found in running_processes but execution exists
        # This can happen if process already finished but wasn't cleaned up
        logger.warning(
            f"Process for execution {execution_id} not found in running_processes, "
            "but execution exists. Cleaning up."
        )
        if execution and execution.script_id:
            self._running_scripts.discard(execution.script_id)
        return False

    async def cleanup_stale_executions(self) -> None:
        """Find executions stuck in RUNNING state and mark them as CRASHED."""
        async with async_session_maker() as db:
            result = await db.execute(
                select(Execution).where(Execution.status == ExecutionStatus.RUNNING.value)
            )
            stale_executions = result.scalars().all()

            if not stale_executions:
                return

            logger.info(f"Cleaning up {len(stale_executions)} stale executions")

            for execution in stale_executions:
                execution.status = ExecutionStatus.FAILED.value
                execution.finished_at = datetime.now(UTC)
                execution.error_message = "Execution interrupted by service restart"

            await db.commit()


# Global instance
executor_service = ExecutorService()
