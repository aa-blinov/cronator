"""Environment management service using uv."""

import asyncio
import logging
import shutil
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Retryable network errors for automatic retry
RETRYABLE_NETWORK_ERRORS = [
    "failed to download",
    "connection timed out",
    "connection refused",
    "temporary failure",
    "network is unreachable",
    "read timed out",
    "ssl error",
    "certificate verify failed",
    "connect timeout",
    "timeout was reached",
]

# Non-retryable errors (configuration issues)
NON_RETRYABLE_ERRORS = [
    "No solution found",
    "not found in the package registry",
    "invalid package name",
    "does not exist",
    "No versions",
]


class EnvironmentService:
    """Service for managing virtual environments using uv."""

    def __init__(self) -> None:
        self.envs_dir = settings.envs_dir
        self.uv_path = settings.uv_path
        self._env_locks: dict[str, asyncio.Lock] = {}
        self._validation_lock = asyncio.Lock()
        # Queues for streaming install output
        self.install_queues: dict[int, asyncio.Queue] = {}
        self._active_installs: dict[int, bool] = {}
        # Mapping script_name -> script_id for coordination with executor
        self._script_name_to_id: dict[str, int] = {}
        # Retry configuration
        self.retry_config = {
            "max_attempts": 3,
            "base_delay": 2.0,  # seconds
            "max_delay": 30.0,  # seconds
            "backoff_factor": 2.0,  # exponential backoff multiplier
        }

    def get_env_path(self, script_name: str) -> Path:
        """Get the path to a script's virtual environment."""
        return self.envs_dir / script_name

    def get_python_path(self, script_name: str) -> Path:
        """Get the path to Python executable in the environment."""
        env_path = self.get_env_path(script_name)
        # Check platform (not just directory existence)
        import sys

        if sys.platform == "win32":
            return env_path / "Scripts" / "python.exe"
        return env_path / "bin" / "python"

    def register_script(self, script_name: str, script_id: int) -> None:
        """Register script name to ID mapping."""
        self._script_name_to_id[script_name] = script_id

    def unregister_script(self, script_name: str) -> None:
        """Unregister script name to ID mapping."""
        self._script_name_to_id.pop(script_name, None)

    def is_script_running(self, script_name: str) -> bool:
        """Check if a script is currently running via executor service."""
        script_id = self._script_name_to_id.get(script_name)
        if script_id is None:
            return False
        
        # Import here to avoid circular dependency
        from app.services.executor import executor_service
        return executor_service.is_script_running(script_id)

    def _get_env_lock(self, script_name: str) -> asyncio.Lock:
        """Get or create a lock for a specific environment."""
        if script_name not in self._env_locks:
            self._env_locks[script_name] = asyncio.Lock()
        return self._env_locks[script_name]

    async def env_exists(self, script_name: str) -> bool:
        """Check if environment exists for a script."""
        python_path = self.get_python_path(script_name)
        return python_path.exists()

    async def create_env(
        self,
        script_name: str,
        python_version: str = "3.11",
    ) -> tuple[bool, str]:
        """
        Create a new virtual environment for a script.

        Note: This method does NOT check if the script is running.
        Use rebuild_env() for manual rebuilds with safety checks.

        Returns:
            Tuple of (success, message)
        """
        lock = self._get_env_lock(script_name)
        async with lock:
            env_path = self.get_env_path(script_name)

            try:
                # Remove existing env if present
                if env_path.exists():
                    logger.info(f"Removing existing environment for {script_name}")
                    try:
                        shutil.rmtree(env_path)
                    except PermissionError as e:
                        # Windows-specific: files may be locked by running process
                        logger.error(
                            f"Cannot remove environment for {script_name}: {e}. "
                            "Files may be in use by running process."
                        )
                        return (
                            False,
                            "Cannot remove environment: files are in use. "
                            "Stop the script and try again.",
                        )
                    except Exception as e:
                        logger.error(f"Error removing environment for {script_name}: {e}")
                        return False, f"Failed to remove existing environment: {str(e)}"

                env_path.mkdir(parents=True, exist_ok=True)

                # Create venv using uv
                # Use --python to specify the version. uv will download it if missing
                cmd = [
                    self.uv_path,
                    "venv",
                    str(env_path),
                    "--python",
                    python_version,
                ]

                logger.info(f"Creating environment for {script_name}: {' '.join(cmd)}")

                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await process.communicate()

                if process.returncode != 0:
                    error_msg = stderr.decode() if stderr else "Unknown error"
                    logger.error(f"Failed to create env for {script_name}: {error_msg}")
                    return False, error_msg

                logger.info(f"Environment created for {script_name}")
                return True, "Environment created successfully"

            except Exception as e:
                logger.exception(f"Error creating environment for {script_name}")
                return False, str(e)

    async def validate_dependencies(
        self,
        dependencies: str,
    ) -> tuple[bool, str, list[str]]:
        """
        Validate dependencies format and resolvability.

        Args:
            dependencies: Newline-separated list of packages

        Returns:
            Tuple of (is_valid, error_message, parsed_packages)
        """
        if not dependencies.strip():
            return True, "", []

        async with self._validation_lock:
            return await self._validate_dependencies_impl(dependencies)

    async def _validate_dependencies_impl(
        self,
        dependencies: str,
    ) -> tuple[bool, str, list[str]]:
        """Internal implementation of dependency validation."""
        try:
            # Parse dependencies
            packages = [
                pkg.strip()
                for pkg in dependencies.strip().split("\n")
                if pkg.strip() and not pkg.strip().startswith("#")
            ]

            if not packages:
                return True, "", []

            # Basic format validation
            invalid_packages = []
            valid_packages = []

            for pkg in packages:
                # Check for obviously invalid syntax
                if any(char in pkg for char in [";", "&", "|", "`", "$"]):
                    invalid_packages.append(f"{pkg} (contains shell characters)")
                    continue

                # Check for valid package name format
                if not pkg or pkg.isspace():
                    invalid_packages.append(f"{pkg} (empty)")
                    continue

                # Basic check for package name structure
                # Should start with alphanumeric or allow brackets for extras
                pkg_name = pkg.split("[")[0].split("=")[0].split(">")[0].split("<")[0].split("!")[0]
                if not pkg_name or not pkg_name[0].isalnum():
                    invalid_packages.append(f"{pkg} (invalid package name)")
                    continue

                valid_packages.append(pkg)

            if invalid_packages:
                return (
                    False,
                    "Invalid package format:\n" + "\n".join(f"• {p}" for p in invalid_packages),
                    valid_packages,
                )

            # Try to resolve with uv (using temp file to avoid stdin issue on Windows)
            import tempfile

            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
                f.write("\n".join(valid_packages))
                temp_file = f.name

            try:
                cmd = [
                    self.uv_path,
                    "pip",
                    "compile",
                    temp_file,
                    "--quiet",
                ]

                logger.info(f"Validating {len(valid_packages)} dependencies with uv")

                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60.0)

                # Check for actual errors (uv writes success messages to stderr too)
                stderr_text = stderr.decode() if stderr else ""
                stdout_text = stdout.decode() if stdout else ""

                # Check for error indicators
                error_indicators = [
                    "No solution found",
                    "not found in the package registry",
                    "No versions",
                    "error:",
                    "failed to download",
                    "Could not find",
                    "does not exist",
                ]

                for indicator in error_indicators:
                    indicator_lower = indicator.lower()
                    if (
                        indicator_lower in stderr_text.lower()
                        or indicator_lower in stdout_text.lower()
                    ):
                        error_output = stderr_text or stdout_text
                        logger.warning(f"Dependency resolution failed: {error_output}")
                        return (
                            False,
                            f"Cannot resolve dependencies:\n{error_output}",
                            valid_packages,
                        )

                # Check return code
                if process.returncode != 0:
                    errors = stderr_text or stdout_text or "Unknown error"
                    logger.warning(
                        f"Dependency resolution failed with code {process.returncode}: {errors}"
                    )
                    return False, f"Resolution error:\n{errors}", valid_packages

                logger.info("Dependencies validated and resolved successfully")
                return (
                    True,
                    f"All {len(valid_packages)} packages are valid and resolvable",
                    valid_packages,
                )

            finally:
                # Clean up temp file
                import os

                try:
                    os.unlink(temp_file)
                except Exception:
                    pass

        except TimeoutError:
            logger.warning("Dependency validation timed out")
            return (
                False,
                "Validation timed out (60s). Try fewer packages or check your network.",
                [],
            )
        except Exception as e:
            logger.exception("Error validating dependencies")
            return False, f"Validation error: {str(e)}", []

    async def install_dependencies(
        self,
        script_name: str,
        dependencies: str,
    ) -> tuple[bool, str]:
        """
        Install dependencies into a script's environment.

        Args:
            script_name: Name of the script
            dependencies: Newline-separated list of packages

        Returns:
            Tuple of (success, output)
        """
        if not dependencies.strip():
            return True, "No dependencies to install"

        lock = self._get_env_lock(script_name)
        async with lock:
            env_path = self.get_env_path(script_name)

            if not env_path.exists():
                return False, "Environment does not exist"

            try:
                # Parse dependencies
                packages = [
                    pkg.strip()
                    for pkg in dependencies.strip().split("\n")
                    if pkg.strip() and not pkg.strip().startswith("#")
                ]

                if not packages:
                    return True, "No valid packages to install"

                # Install using uv pip
                cmd = [
                    self.uv_path,
                    "pip",
                    "install",
                    "--python",
                    str(self.get_python_path(script_name)),
                    *packages,
                ]

                logger.info(f"Installing dependencies for {script_name}: {packages}")

                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await process.communicate()

                output = stdout.decode() if stdout else ""
                errors = stderr.decode() if stderr else ""

                # Check for errors even if returncode is 0
                error_indicators = [
                    "No solution found",
                    "not found in the package registry",
                    "Could not find",
                    "No versions",
                    "does not exist",
                    "error:",
                    "failed to download",
                ]

                errors_found = []
                for indicator in error_indicators:
                    if indicator.lower() in errors.lower() or indicator.lower() in output.lower():
                        errors_found.append(indicator)

                if errors_found or process.returncode != 0:
                    error_msg = errors or output or "Installation failed"
                    logger.error(f"Failed to install deps for {script_name}: {error_msg}")
                    return False, error_msg

                logger.info(f"Dependencies installed for {script_name}")
                return True, output or "Dependencies installed successfully"

            except Exception as e:
                logger.exception(f"Error installing dependencies for {script_name}")
                return False, str(e)

    async def setup_environment(
        self,
        script_name: str,
        python_version: str = "3.11",
        dependencies: str = "",
    ) -> tuple[bool, str]:
        """
        Create environment and install dependencies.

        This is the main method to call for setting up a script's environment.
        """
        # Validate dependencies first
        if dependencies.strip():
            is_valid, error_msg, _ = await self.validate_dependencies(dependencies)
            if not is_valid:
                return False, f"Invalid dependencies: {error_msg}"

        # Create environment
        success, message = await self.create_env(script_name, python_version)
        if not success:
            return False, f"Failed to create environment: {message}"

        # Install cronator_lib into the environment
        cronator_lib_path = settings.base_dir / "cronator_lib"
        if cronator_lib_path.exists():
            success, output = await self._install_cronator_lib(script_name)
            if not success:
                logger.warning(f"Failed to install cronator_lib: {output}")

        # Install user dependencies
        if dependencies.strip():
            success, output = await self.install_dependencies(script_name, dependencies)
            if not success:
                return False, f"Failed to install dependencies: {output}"
            message += f"\n{output}"

        return True, message

    async def _install_cronator_lib(self, script_name: str) -> tuple[bool, str]:
        """Install the cronator_lib package into the environment."""
        cronator_lib_path = settings.base_dir / "cronator_lib"

        cmd = [
            self.uv_path,
            "pip",
            "install",
            "--python",
            str(self.get_python_path(script_name)),
            "-e",
            str(cronator_lib_path),
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                return False, stderr.decode() if stderr else "Unknown error"
            return True, "cronator_lib installed"

        except Exception as e:
            return False, str(e)

    async def delete_env(self, script_name: str) -> tuple[bool, str]:
        """Delete a script's virtual environment."""
        # Check if script is running
        if self.is_script_running(script_name):
            return False, "Cannot delete environment while script is running"

        env_path = self.get_env_path(script_name)

        try:
            if env_path.exists():
                try:
                    shutil.rmtree(env_path)
                    logger.info(f"Deleted environment for {script_name}")
                    self.unregister_script(script_name)
                    return True, "Environment deleted"
                except PermissionError as e:
                    logger.error(
                        f"Cannot delete environment for {script_name}: {e}. "
                        "Files may be in use."
                    )
                    return (
                        False,
                        "Cannot delete environment: files are in use. "
                        "Stop the script and try again.",
                    )
            self.unregister_script(script_name)
            return True, "Environment did not exist"
        except Exception as e:
            logger.exception(f"Error deleting environment for {script_name}")
            return False, str(e)

    async def get_installed_packages(self, script_name: str) -> list[str]:
        """Get list of installed packages in an environment."""
        python_path = self.get_python_path(script_name)

        if not python_path.exists():
            return []

        try:
            cmd = [
                self.uv_path,
                "pip",
                "list",
                "--python",
                str(python_path),
                "--format",
                "freeze",
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate()

            if process.returncode == 0 and stdout:
                return [line.strip() for line in stdout.decode().split("\n") if line.strip()]
            return []

        except Exception:
            return []

    # --- Streaming install methods ---

    def is_installing(self, script_id: int) -> bool:
        """Check if installation is in progress for a script."""
        return self._active_installs.get(script_id, False)

    async def setup_environment_streaming(
        self,
        script_id: int,
        script_name: str,
        python_version: str = "3.11",
        dependencies: str = "",
    ) -> tuple[bool, str]:
        """
        Create environment and install dependencies with streaming output.

        Output is sent to install_queues[script_id].
        """
        queue = self.install_queues.get(script_id)

        async def send_log(message: str) -> None:
            if queue:
                await queue.put(("log", message))

        async def send_error(message: str) -> None:
            if queue:
                await queue.put(("error", message))

        self._active_installs[script_id] = True

        try:
            # Validate dependencies first
            if dependencies.strip():
                await send_log("📋 Validating dependencies...")
                is_valid, error_msg, packages = await self.validate_dependencies(dependencies)
                if not is_valid:
                    await send_error(f"❌ Invalid dependencies: {error_msg}")
                    return False, f"Invalid dependencies: {error_msg}"
                await send_log(f"✓ Dependencies valid: {', '.join(packages)}")

            # Create environment
            await send_log(f"🔧 Creating virtual environment (Python {python_version})...")
            success, message = await self._create_env_streaming(
                script_id, script_name, python_version
            )
            if not success:
                await send_error(f"❌ Failed to create environment: {message}")
                return False, f"Failed to create environment: {message}"
            await send_log("✓ Environment created")

            # Install cronator_lib
            cronator_lib_path = settings.base_dir / "cronator_lib"
            if cronator_lib_path.exists():
                await send_log("📦 Installing cronator_lib...")
                success, output = await self._install_cronator_lib_streaming(script_id, script_name)
                if success:
                    await send_log("✓ cronator_lib installed")
                else:
                    await send_log(f"⚠ Warning: cronator_lib install failed: {output}")

            # Install user dependencies
            if dependencies.strip():
                await send_log("📦 Installing dependencies...")
                success, output = await self._install_dependencies_streaming(
                    script_id, script_name, dependencies
                )
                if not success:
                    await send_error(f"❌ Failed to install dependencies: {output}")
                    return False, f"Failed to install dependencies: {output}"
                await send_log("✓ Dependencies installed successfully")

            await send_log("🎉 Environment setup complete!")
            return True, "Environment setup complete"

        except Exception as e:
            await send_error(f"❌ Error: {str(e)}")
            return False, str(e)
        finally:
            self._active_installs[script_id] = False
            if queue:
                await queue.put(("done", ""))

    async def _create_env_streaming(
        self,
        script_id: int,
        script_name: str,
        python_version: str,
    ) -> tuple[bool, str]:
        """Create environment with streaming output."""
        queue = self.install_queues.get(script_id)
        lock = self._get_env_lock(script_name)

        async with lock:
            env_path = self.get_env_path(script_name)

            try:
                if env_path.exists():
                    shutil.rmtree(env_path)
                env_path.mkdir(parents=True, exist_ok=True)

                cmd = [
                    self.uv_path,
                    "venv",
                    str(env_path),
                    "--python",
                    python_version,
                ]

                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                # Stream stderr (uv outputs to stderr)
                async def read_stream(stream, prefix=""):
                    while True:
                        line = await stream.readline()
                        if not line:
                            break
                        text = line.decode().rstrip()
                        if queue and text:
                            await queue.put(("log", f"  {prefix}{text}"))

                await asyncio.gather(
                    read_stream(process.stdout),
                    read_stream(process.stderr),
                )

                await process.wait()

                if process.returncode != 0:
                    return False, f"uv venv failed with code {process.returncode}"

                return True, "Environment created"

            except Exception as e:
                return False, str(e)

    async def _install_cronator_lib_streaming(
        self,
        script_id: int,
        script_name: str,
    ) -> tuple[bool, str]:
        """Install cronator_lib with streaming output."""
        queue = self.install_queues.get(script_id)
        cronator_lib_path = settings.base_dir / "cronator_lib"

        cmd = [
            self.uv_path,
            "pip",
            "install",
            "--python",
            str(self.get_python_path(script_name)),
            "-e",
            str(cronator_lib_path),
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            async def read_stream(stream):
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    text = line.decode().rstrip()
                    if queue and text:
                        await queue.put(("log", f"  {text}"))

            await asyncio.gather(
                read_stream(process.stdout),
                read_stream(process.stderr),
            )

            await process.wait()

            if process.returncode != 0:
                return False, f"pip install failed with code {process.returncode}"
            return True, "cronator_lib installed"

        except Exception as e:
            return False, str(e)

    async def _install_dependencies_streaming(
        self,
        script_id: int,
        script_name: str,
        dependencies: str,
    ) -> tuple[bool, str]:
        """Install dependencies with streaming output and automatic retry on network errors."""
        queue = self.install_queues.get(script_id)
        lock = self._get_env_lock(script_name)

        async with lock:
            env_path = self.get_env_path(script_name)

            if not env_path.exists():
                return False, "Environment does not exist"

            try:
                packages = [
                    pkg.strip()
                    for pkg in dependencies.strip().split("\n")
                    if pkg.strip() and not pkg.strip().startswith("#")
                ]

                if not packages:
                    return True, "No packages to install"

                cmd = [
                    self.uv_path,
                    "pip",
                    "install",
                    "--python",
                    str(self.get_python_path(script_name)),
                    *packages,
                ]

                # Retry loop for network errors
                max_attempts = self.retry_config["max_attempts"]
                base_delay = self.retry_config["base_delay"]
                backoff_factor = self.retry_config["backoff_factor"]
                max_delay = self.retry_config["max_delay"]

                last_error = ""

                for attempt in range(1, max_attempts + 1):
                    if attempt > 1 and queue:
                        await queue.put(("log", f"\\n🔄 Retry attempt {attempt}/{max_attempts}..."))

                    process = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )

                    # Collect output for error checking
                    stdout_lines = []
                    stderr_lines = []

                    async def read_stream(stream, lines_list):
                        while True:
                            line = await stream.readline()
                            if not line:
                                break
                            text = line.decode().rstrip()
                            lines_list.append(text)
                            if queue and text:
                                await queue.put(("log", f"  {text}"))

                    await asyncio.gather(
                        read_stream(process.stdout, stdout_lines),
                        read_stream(process.stderr, stderr_lines),
                    )

                    await process.wait()

                    # Success case
                    if process.returncode == 0:
                        logger.info(
                            f"Dependencies installed for {script_name} "
                            f"(attempt {attempt}/{max_attempts})"
                        )
                        return True, "Dependencies installed"

                    # Failed - check if retryable
                    all_output = "\\n".join(stdout_lines + stderr_lines).lower()
                    last_error = f"pip install failed with code {process.returncode}"

                    # Check for retryable network errors
                    is_retryable = any(
                        error_indicator in all_output
                        for error_indicator in RETRYABLE_NETWORK_ERRORS
                    )

                    # Check for non-retryable errors (config issues)
                    is_non_retryable = any(
                        error_indicator.lower() in all_output
                        for error_indicator in NON_RETRYABLE_ERRORS
                    )

                    if is_non_retryable:
                        logger.warning(f"Non-retryable error for {script_name}: {last_error}")
                        if queue:
                            error_msg = (
                                "\\n❌ Installation failed with configuration error (not retrying)"
                            )
                            await queue.put(("log", error_msg))
                        return False, last_error

                    if not is_retryable or attempt == max_attempts:
                        # Last attempt or not retryable
                        logger.error(
                            f"Installation failed for {script_name} after {attempt} attempt(s): "
                            f"{last_error}"
                        )
                        return False, last_error

                    # Calculate delay with exponential backoff
                    delay = min(base_delay * (backoff_factor ** (attempt - 1)), max_delay)

                    if queue:
                        await queue.put(
                            ("log", f"⚠️  Network error detected. Retrying in {delay:.1f}s...")
                        )

                    logger.info(
                        f"Retrying installation for {script_name} in {delay:.1f}s "
                        f"(attempt {attempt}/{max_attempts})"
                    )
                    await asyncio.sleep(delay)

                # This should not be reached, but for safety
                return False, last_error or "Installation failed"

            except Exception as e:
                logger.exception(f"Error installing dependencies for {script_name}")
                return False, str(e)


# Global instance
environment_service = EnvironmentService()
