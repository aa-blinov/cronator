"""Environment management service using uv."""

import asyncio
import logging
import shutil
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class EnvironmentService:
    """Service for managing virtual environments using uv."""

    def __init__(self) -> None:
        self.envs_dir = settings.envs_dir
        self.uv_path = settings.uv_path
        self._env_locks: dict[str, asyncio.Lock] = {}
        self._validation_lock = asyncio.Lock()

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

        Returns:
            Tuple of (success, message)
        """
        lock = self._get_env_lock(script_name)
        async with lock:
            env_path = self.get_env_path(script_name)

            try:
                # Remove existing env if present
                if env_path.exists():
                    shutil.rmtree(env_path)

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

                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30.0)

                # Check for actual errors (uv writes success messages to stderr too)
                stderr_text = stderr.decode() if stderr else ""

                # Check for error indicators in stderr
                if (
                    "No solution found" in stderr_text
                    or "not found in the package registry" in stderr_text
                ):
                    logger.warning(f"Dependency resolution failed: {stderr_text}")
                    return False, f"Cannot resolve dependencies:\n{stderr_text}", valid_packages

                if process.returncode != 0 and "Resolved" not in stderr_text:
                    errors = stderr_text or "Unknown error"
                    logger.warning(f"Dependency resolution failed: {errors}")
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
                "Validation timed out (30s). Try fewer packages or check your network.",
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

                if process.returncode != 0:
                    logger.error(f"Failed to install deps for {script_name}: {errors}")
                    return False, errors or "Installation failed"

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
        env_path = self.get_env_path(script_name)

        try:
            if env_path.exists():
                shutil.rmtree(env_path)
                logger.info(f"Deleted environment for {script_name}")
                return True, "Environment deleted"
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


# Global instance
environment_service = EnvironmentService()
