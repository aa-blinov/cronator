"""Unit tests for Executor service."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.execution import ExecutionStatus
from app.services.executor import ExecutorService


class TestExecutorService:
    """Tests for ExecutorService."""

    def test_init(self):
        """Test ExecutorService initialization."""
        service = ExecutorService()
        assert service.running_processes == {}
        assert service.output_queues == {}
        assert service.stream_states == {}

    def test_is_script_running_false(self):
        """Test is_script_running when not running."""
        service = ExecutorService()
        assert service.is_script_running(1) is False

    def test_is_script_running_true(self):
        """Test is_script_running when running."""
        service = ExecutorService()
        # The actual implementation uses _running_scripts set
        service._running_scripts.add(1)
        assert service.is_script_running(1) is True

    def test_get_script_lock_creates_new(self):
        """Test that _get_script_lock creates new lock."""
        service = ExecutorService()
        lock1 = service._get_script_lock(1)
        assert isinstance(lock1, asyncio.Lock)

    def test_get_script_lock_returns_same(self):
        """Test that _get_script_lock returns same lock for same script."""
        service = ExecutorService()
        lock1 = service._get_script_lock(1)
        lock2 = service._get_script_lock(1)
        assert lock1 is lock2

    def test_get_script_lock_different_scripts(self):
        """Test that different scripts get different locks."""
        service = ExecutorService()
        lock1 = service._get_script_lock(1)
        lock2 = service._get_script_lock(2)
        assert lock1 is not lock2

    @pytest.mark.asyncio
    async def test_cancel_execution_not_running(self):
        """Test canceling execution that's not running."""
        service = ExecutorService()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("app.services.executor.async_session_maker", return_value=mock_session_ctx):
            result = await service.cancel_execution(999)
            assert result is False

    @pytest.mark.asyncio
    async def test_cancel_execution_running(self):
        """Test canceling a running execution."""
        service = ExecutorService()

        # Create mock process - cancel uses execution_id as key and kill()
        mock_process = MagicMock()
        mock_process.kill = MagicMock()
        mock_process.returncode = None

        execution_id = 1
        service.running_processes[execution_id] = mock_process

        # Create a proper async context manager mock
        mock_execution = MagicMock()
        mock_execution.status = ExecutionStatus.RUNNING.value

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_execution)

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("app.services.executor.async_session_maker", return_value=mock_session_ctx):
            result = await service.cancel_execution(execution_id)
            assert result is True
            mock_process.kill.assert_called_once()
            assert mock_execution.status == ExecutionStatus.CANCELLED.value
            assert mock_execution.error_message == "Cancelled by user"

    @pytest.mark.asyncio
    async def test_cancel_execution_commits_cancelled_status_before_kill(self):
        """Cancellation persists `cancelled` before the process exits."""
        service = ExecutorService()

        execution_id = 1
        call_order: list[tuple[str, str]] = []

        mock_process = MagicMock()
        mock_execution = MagicMock()
        mock_execution.id = execution_id
        mock_execution.script_id = 7
        mock_execution.status = ExecutionStatus.RUNNING.value
        mock_execution.finished_at = None
        mock_execution.error_message = None

        def kill_side_effect():
            call_order.append(("kill", mock_execution.status))

        mock_process.kill.side_effect = kill_side_effect
        service.running_processes[execution_id] = mock_process

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_execution)

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def commit_side_effect():
            call_order.append(("commit", mock_execution.status))

        mock_db.commit.side_effect = commit_side_effect

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("app.services.executor.async_session_maker", return_value=mock_session_ctx):
            result = await service.cancel_execution(execution_id)

        assert result is True
        assert call_order == [
            ("commit", ExecutionStatus.CANCELLED.value),
            ("kill", ExecutionStatus.CANCELLED.value),
        ]

    @pytest.mark.asyncio
    async def test_finish_execution_keeps_cancelled_status_and_sets_duration(self):
        """Cancelled executions keep their status while still capturing final metadata."""
        service = ExecutorService()

        execution = MagicMock()
        execution.id = 42
        execution.status = ExecutionStatus.CANCELLED.value
        execution.exit_code = None
        execution.stdout = ""
        execution.stderr = ""
        execution.finished_at = datetime.now(UTC)
        execution.duration_ms = None
        execution.error_message = "Cancelled by user"

        mock_db = AsyncMock()
        mock_db.refresh = AsyncMock()
        mock_db.commit = AsyncMock()

        start_time = execution.finished_at - timedelta(seconds=4)

        await service._finish_execution(
            mock_db,
            execution,
            status=ExecutionStatus.FAILED,
            exit_code=-9,
            stdout="partial output\n",
            stderr="",
            start_time=start_time,
        )

        assert execution.status == ExecutionStatus.CANCELLED.value
        assert execution.exit_code == -9
        assert execution.stdout == "partial output\n"
        assert execution.duration_ms == 4000
        assert execution.error_message == "Cancelled by user"

    @pytest.mark.asyncio
    async def test_cleanup_stale_executions(self):
        """Test cleanup of stale executions runs without error."""
        service = ExecutorService()

        # Create proper mock for scalars().all()
        mock_scalars = MagicMock()
        mock_scalars.all = MagicMock(return_value=[])

        mock_result = MagicMock()
        mock_result.scalars = MagicMock(return_value=mock_scalars)

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("app.services.executor.async_session_maker", return_value=mock_session_ctx):
            # Should not raise
            await service.cleanup_stale_executions()


class TestExecutorServiceScriptPath:
    """Tests for script path handling in ExecutorService."""

    @pytest.mark.asyncio
    async def test_get_script_path_with_content(self, script_factory):
        """Test getting path for script with content."""
        script = await script_factory(
            name="path_test",
            content="print('test')",
            path="/scripts/path_test/main.py",
        )

        service = ExecutorService()
        path = service._get_script_path(script)

        assert path is not None
        assert "path_test" in str(path)


class TestSubprocessEnvIsolation:
    """
    Проверяет что subprocess получает только явно разрешённые переменные окружения,
    а секреты Cronator (DATABASE_URL, ADMIN_PASSWORD и т.д.) не утекают в пользовательские скрипты.
    """

    # ------------------------------------------------------------------ helpers

    def _make_script(self, environment_vars: str | None = None) -> MagicMock:
        script = MagicMock()
        script.id = 1
        script.name = "test_script"
        script.path = None  # генерируется автоматически
        script.python_version = "3.12"
        script.dependencies = None
        script.timeout = 60
        script.environment_vars = environment_vars
        script.working_directory = None
        return script

    def _make_execution(self) -> MagicMock:
        execution = MagicMock()
        execution.id = 42
        execution.status = ExecutionStatus.RUNNING.value
        execution.exit_code = None
        execution.stdout = ""
        execution.stderr = ""
        execution.finished_at = None
        return execution

    def _make_db_ctx(self, script: MagicMock, execution: MagicMock) -> MagicMock:
        """Мок async_session_maker(): два вызова execute() → script, execution."""
        res_script = MagicMock()
        res_script.scalar_one_or_none.return_value = script

        res_exec = MagicMock()
        res_exec.scalar_one_or_none.return_value = execution

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[res_script, res_exec])
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()  # _finish_execution вызывает db.refresh(execution)
        mock_db.add = MagicMock()

        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_db)
        ctx.__aexit__ = AsyncMock(return_value=None)
        return ctx

    def _make_process(self) -> MagicMock:
        """Мок subprocess — завершается мгновенно, вывода нет."""
        proc = MagicMock()
        proc.pid = 12345
        proc.returncode = 0
        proc.stdout = AsyncMock()
        proc.stdout.readline = AsyncMock(return_value=b"")
        proc.stderr = AsyncMock()
        proc.stderr.readline = AsyncMock(return_value=b"")
        proc.wait = AsyncMock(return_value=0)
        return proc

    def _make_settings(self) -> MagicMock:
        """Мок settings с нужными путями."""
        exec_artifacts = MagicMock(spec=Path)
        exec_artifacts.mkdir = MagicMock()
        exec_artifacts.__str__ = lambda self: "/tmp/artifacts/42"

        artifacts_dir = MagicMock(spec=Path)
        artifacts_dir.__truediv__ = MagicMock(return_value=exec_artifacts)

        s = MagicMock()
        s.base_dir = Path("/app")
        s.artifacts_dir = artifacts_dir
        s.max_log_size = 1_000_000
        return s

    async def _run_and_capture_env(
        self,
        script: MagicMock,
        execution: MagicMock,
    ) -> dict:
        """
        Запускает _run_script с замоканным окружением и возвращает
        словарь env, который был передан в asyncio.create_subprocess_exec.
        """
        captured: dict = {}

        async def fake_subprocess(*args, **kwargs):
            captured.update(kwargs.get("env", {}))
            return self._make_process()

        python_path = MagicMock(spec=Path)
        python_path.exists.return_value = True
        python_path.__str__ = lambda self: "/venvs/test_script/bin/python"

        script_path = MagicMock(spec=Path)
        script_path.exists.return_value = True
        script_path.__str__ = lambda self: "/scripts/test_script/main.py"
        script_path.parent = Path("/scripts/test_script")

        service = ExecutorService()

        with (
            patch(
                "app.services.executor.async_session_maker",
                return_value=self._make_db_ctx(script, execution),
            ),
            patch("app.services.executor.environment_service") as mock_env_svc,
            patch.object(ExecutorService, "_get_script_path", return_value=script_path),
            patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=fake_subprocess)),
            patch("app.services.executor.settings", self._make_settings()),
            # Отключаем алертинг — открывает отдельные сессии, не нужен для env-тестов
            patch.object(ExecutorService, "_send_success_alert", new=AsyncMock()),
            patch.object(ExecutorService, "_send_failure_alert", new=AsyncMock()),
        ):
            mock_env_svc.env_exists = AsyncMock(return_value=True)
            mock_env_svc.get_python_path.return_value = python_path

            await service._run_script(script_id=1, execution_id=42)

        return captured

    # ------------------------------------------------------------------ tests

    @pytest.mark.asyncio
    async def test_parent_secrets_not_leaked_to_subprocess(self, monkeypatch):
        """Секреты Cronator не должны попадать в subprocess пользовательского скрипта."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://admin:supersecret@db/cronator")
        monkeypatch.setenv("ADMIN_PASSWORD", "super_secret_password")
        monkeypatch.setenv("SECRET_KEY", "my_very_secret_key")
        monkeypatch.setenv("CRONATOR_INTERNAL_TOKEN", "internal_token")

        env = await self._run_and_capture_env(self._make_script(), self._make_execution())

        assert "DATABASE_URL" not in env, "DATABASE_URL утёк в subprocess!"
        assert "ADMIN_PASSWORD" not in env, "ADMIN_PASSWORD утёк в subprocess!"
        assert "SECRET_KEY" not in env, "SECRET_KEY утёк в subprocess!"
        assert "CRONATOR_INTERNAL_TOKEN" not in env, "CRONATOR_INTERNAL_TOKEN утёк в subprocess!"

    @pytest.mark.asyncio
    async def test_oracle_client_vars_present_in_subprocess(self):
        """Subprocess должен получить переменные Oracle client для работы cx_Oracle."""
        env = await self._run_and_capture_env(self._make_script(), self._make_execution())

        assert "LD_LIBRARY_PATH" in env
        assert "/usr/lib/instantclient" in env["LD_LIBRARY_PATH"]
        assert env.get("ORACLE_HOME") == "/usr/lib/instantclient"
        assert env.get("ORACLE_BASE") == "/usr/lib/instantclient"
        assert env.get("TNS_ADMIN") == "/usr/lib/instantclient"

    @pytest.mark.asyncio
    async def test_user_defined_env_vars_passed_to_subprocess(self):
        """Пользовательские переменные из script.environment_vars должны попасть в subprocess."""
        script = self._make_script(
            environment_vars='{"MY_API_KEY": "hello123", "DB_HOST": "prod-db"}'
        )

        env = await self._run_and_capture_env(script, self._make_execution())

        assert env.get("MY_API_KEY") == "hello123"
        assert env.get("DB_HOST") == "prod-db"

    @pytest.mark.asyncio
    async def test_cronator_context_vars_passed_to_subprocess(self):
        """Контекстные переменные Cronator (script_id, execution_id и т.д.) должны быть в subprocess."""
        env = await self._run_and_capture_env(self._make_script(), self._make_execution())

        assert env.get("CRONATOR_SCRIPT_ID") == "1"
        assert env.get("CRONATOR_EXECUTION_ID") == "42"
        assert env.get("CRONATOR_SCRIPT_NAME") == "test_script"

    @pytest.mark.asyncio
    async def test_only_allowed_system_vars_present(self, monkeypatch):
        """
        Проверяет что в subprocess попадают только разрешённые системные переменные
        (PATH, HOME, LANG, TZ), а не весь os.environ родительского процесса.
        """
        # Добавляем "лишние" системные переменные в родительский процесс
        monkeypatch.setenv("RANDOM_SYSTEM_VAR", "should_not_leak")
        monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
        monkeypatch.setenv("VIRTUAL_ENV", "/some/venv")

        env = await self._run_and_capture_env(self._make_script(), self._make_execution())

        assert "RANDOM_SYSTEM_VAR" not in env
        assert "VIRTUAL_ENV" not in env

        # Разрешённые системные переменные на месте
        assert "PATH" in env
        assert "HOME" in env
        assert "LANG" in env
        assert "TZ" in env
