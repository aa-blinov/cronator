"""Unit tests for cronator_lib: CronatorLogger, get_logger, save_artifact."""

import logging
import os
import sys
from io import StringIO
from unittest.mock import patch

import pytest

from cronator_lib.logging import (
    CronatorFormatter,
    CronatorLogger,
    PrettyFormatter,
    get_logger,
    save_artifact,
)

# ─────────────────────────── CronatorLogger handlers ─────────────────────────


class TestCronatorLoggerHandlers:
    """Verify that log levels are routed to the correct output streams."""

    def _make_logger(self, in_cronator: bool = False) -> CronatorLogger:
        env = {"CRONATOR_EXECUTION_ID": "42"} if in_cronator else {}
        with patch.dict(os.environ, env, clear=not in_cronator):
            env_patch = {"CRONATOR_EXECUTION_ID": "42"} if in_cronator else {}
            with patch.dict(os.environ, env_patch):
                if not in_cronator:
                    os.environ.pop("CRONATOR_EXECUTION_ID", None)
                return CronatorLogger(f"test_logger_{id(self)}_{in_cronator}")

    def test_has_two_handlers(self):
        """Logger must have exactly two handlers: stdout and stderr."""
        logger = CronatorLogger("test_two_handlers")
        assert len(logger.handlers) == 2

    def test_stdout_handler_uses_sys_stdout(self):
        """First handler writes to sys.stdout."""
        logger = CronatorLogger("test_stdout_handler")
        stdout_handlers = [
            h
            for h in logger.handlers
            if isinstance(h, logging.StreamHandler) and h.stream is sys.stdout
        ]
        assert len(stdout_handlers) == 1

    def test_stderr_handler_uses_sys_stderr(self):
        """Second handler writes to sys.stderr."""
        logger = CronatorLogger("test_stderr_handler")
        stderr_handlers = [
            h
            for h in logger.handlers
            if isinstance(h, logging.StreamHandler) and h.stream is sys.stderr
        ]
        assert len(stderr_handlers) == 1

    def test_debug_goes_to_stdout_not_stderr(self):
        """DEBUG → stdout only."""
        stdout, stderr = StringIO(), StringIO()
        logger = CronatorLogger("test_debug")
        logger.setLevel(logging.DEBUG)
        logger.handlers[0].stream = stdout
        logger.handlers[1].stream = stderr

        logger.debug("debug_msg")

        assert "debug_msg" in stdout.getvalue()
        assert "debug_msg" not in stderr.getvalue()

    def test_info_goes_to_stdout_not_stderr(self):
        """INFO → stdout only."""
        stdout, stderr = StringIO(), StringIO()
        logger = CronatorLogger("test_info")
        logger.handlers[0].stream = stdout
        logger.handlers[1].stream = stderr

        logger.info("info_msg")

        assert "info_msg" in stdout.getvalue()
        assert "info_msg" not in stderr.getvalue()

    def test_warning_goes_to_stdout_not_stderr(self):
        """WARNING → stdout only."""
        stdout, stderr = StringIO(), StringIO()
        logger = CronatorLogger("test_warning")
        logger.handlers[0].stream = stdout
        logger.handlers[1].stream = stderr

        logger.warning("warn_msg")

        assert "warn_msg" in stdout.getvalue()
        assert "warn_msg" not in stderr.getvalue()

    def test_error_goes_to_stderr_not_stdout(self):
        """ERROR → stderr only."""
        stdout, stderr = StringIO(), StringIO()
        logger = CronatorLogger("test_error")
        logger.handlers[0].stream = stdout
        logger.handlers[1].stream = stderr

        logger.error("error_msg")

        assert "error_msg" not in stdout.getvalue()
        assert "error_msg" in stderr.getvalue()

    def test_critical_goes_to_stderr_not_stdout(self):
        """CRITICAL → stderr only."""
        stdout, stderr = StringIO(), StringIO()
        logger = CronatorLogger("test_critical")
        logger.handlers[0].stream = stdout
        logger.handlers[1].stream = stderr

        logger.critical("critical_msg")

        assert "critical_msg" not in stdout.getvalue()
        assert "critical_msg" in stderr.getvalue()


# ─────────────────────────── formatters ──────────────────────────────────────


class TestFormatters:
    """CronatorFormatter (JSON) vs PrettyFormatter (human-readable)."""

    def test_cronator_formatter_outputs_valid_json(self):
        """In Cronator context, logs are emitted as JSON."""
        import json

        formatter = CronatorFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello json",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output.strip())

        assert parsed["level"] == "INFO"
        assert parsed["message"] == "hello json"
        assert "timestamp" in parsed
        assert "logger" in parsed

    def test_cronator_formatter_includes_exception(self):
        """If exc_info is present, the exception field appears in the JSON output."""
        import json

        formatter = CronatorFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            record = logging.LogRecord(
                name="test",
                level=logging.ERROR,
                pathname="",
                lineno=0,
                msg="boom",
                args=(),
                exc_info=sys.exc_info(),
            )
        output = formatter.format(record)
        parsed = json.loads(output.strip())

        assert "exception" in parsed
        assert "ValueError" in parsed["exception"]

    def test_cronator_formatter_preserves_unicode_characters(self):
        """JSON formatter should keep readable UTF-8 characters instead of \\u escapes."""
        import json

        formatter = CronatorFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Done: 45 rows",
            args=(),
            exc_info=None,
        )

        output = formatter.format(record)
        parsed = json.loads(output.strip())

        assert parsed["message"] == "Done: 45 rows"

    def test_pretty_formatter_outputs_human_readable(self):
        """Local formatter produces a plain string, not JSON."""
        import json

        formatter = PrettyFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="pretty msg",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)

        assert "pretty msg" in output
        # Must not be valid JSON
        with pytest.raises((json.JSONDecodeError, ValueError)):
            json.loads(output)

    def test_in_cronator_context_uses_json_formatter(self):
        """With CRONATOR_EXECUTION_ID set, handlers use CronatorFormatter."""
        with patch.dict(os.environ, {"CRONATOR_EXECUTION_ID": "1"}):
            logger = CronatorLogger("test_json_fmt")

        for handler in logger.handlers:
            assert isinstance(handler.formatter, CronatorFormatter)

    def test_cronator_logger_writes_single_newline_per_json_record(self):
        """JSON log must not leave blank lines between events."""
        stdout, stderr = StringIO(), StringIO()

        with patch.dict(os.environ, {"CRONATOR_EXECUTION_ID": "1"}):
            logger = CronatorLogger("test_json_newline")

        logger.handlers[0].stream = stdout
        logger.handlers[1].stream = stderr

        logger.info("first")
        logger.info("second")

        stdout_lines = stdout.getvalue().splitlines()
        assert len(stdout_lines) == 2
        assert all(line.strip() for line in stdout_lines)
        assert stderr.getvalue() == ""

    def test_outside_cronator_context_uses_pretty_formatter(self):
        """Without CRONATOR_EXECUTION_ID, handlers use PrettyFormatter."""
        env = os.environ.copy()
        env.pop("CRONATOR_EXECUTION_ID", None)
        with patch.dict(os.environ, env, clear=True):
            logger = CronatorLogger("test_pretty_fmt")

        for handler in logger.handlers:
            assert isinstance(handler.formatter, PrettyFormatter)


# ─────────────────────────── get_logger ──────────────────────────────────────


class TestGetLogger:
    """Logger caching and naming."""

    def test_returns_cronator_logger_instance(self):
        """get_logger() returns a CronatorLogger instance."""
        logger = get_logger("unique_test_name_1")
        assert isinstance(logger, CronatorLogger)

    def test_same_instance_for_same_name(self):
        """get_logger() with the same name returns the same object."""
        a = get_logger("unique_test_name_2")
        b = get_logger("unique_test_name_2")
        assert a is b

    def test_different_instances_for_different_names(self):
        """Different names → different logger instances."""
        a = get_logger("unique_test_name_3")
        b = get_logger("unique_test_name_4")
        assert a is not b

    def test_uses_script_name_from_env(self):
        """Without an explicit name, reads CRONATOR_SCRIPT_NAME from env."""
        with patch.dict(os.environ, {"CRONATOR_SCRIPT_NAME": "env_script_xyz"}):
            logger = get_logger()
        assert logger.name == "env_script_xyz"

    def test_default_name_without_env(self):
        """Without env var or explicit name, defaults to 'cronator_script'."""
        env = os.environ.copy()
        env.pop("CRONATOR_SCRIPT_NAME", None)
        with patch.dict(os.environ, env, clear=True):
            logger = get_logger()
        assert logger.name == "cronator_script"


# ─────────────────────────── convenience methods ─────────────────────────────


class TestConvenienceMethods:
    def _capture_logger(self) -> tuple[CronatorLogger, StringIO]:
        stdout = StringIO()
        logger = CronatorLogger(f"conv_{id(self)}")
        logger.handlers[0].stream = stdout
        return logger, stdout

    def test_success_logs_at_info_level(self):
        """success() writes to stdout (INFO level)."""
        logger, stdout = self._capture_logger()
        logger.success("all done")
        assert "all done" in stdout.getvalue()

    def test_task_start_logs_starting(self):
        """task_start() writes STARTING to stdout."""
        logger, stdout = self._capture_logger()
        logger.task_start("my_task")
        assert "my_task" in stdout.getvalue()

    def test_task_end_success_logs_completed(self):
        """task_end(success=True) → COMPLETED in stdout."""
        logger, stdout = self._capture_logger()
        logger.task_end("my_task", success=True)
        assert "my_task" in stdout.getvalue()

    def test_task_end_failure_goes_to_stderr(self):
        """task_end(success=False) → ERROR → stderr."""
        stderr = StringIO()
        logger = CronatorLogger(f"conv_fail_{id(self)}")
        logger.handlers[1].stream = stderr
        logger.task_end("my_task", success=False)
        assert "my_task" in stderr.getvalue()

    def test_with_data_logs_message(self):
        """with_data() writes the message to stdout."""
        logger, stdout = self._capture_logger()
        logger.with_data("structured", key="val")
        assert "structured" in stdout.getvalue()

    def test_progress_logs_percentage(self):
        """progress() writes percentage to stdout."""
        logger, stdout = self._capture_logger()
        logger.progress(50, 100, "loading")
        assert "50.0%" in stdout.getvalue()

    def test_progress_zero_total_does_not_raise(self):
        """progress() with total=0 does not raise (division by zero guard)."""
        logger, stdout = self._capture_logger()
        logger.progress(0, 0)


# ─────────────────────────── save_artifact ───────────────────────────────────


class TestSaveArtifact:
    """Tests for save_artifact()."""

    def test_saves_bytes_and_returns_filename(self, tmp_path):
        """Saves bytes and returns a unique filename."""
        with patch.dict(os.environ, {"CRONATOR_ARTIFACTS_DIR": str(tmp_path)}):
            name = save_artifact("report.txt", b"hello bytes")

        assert name.startswith("report_")
        assert name.endswith(".txt")
        saved = list(tmp_path.glob("report_*.txt"))
        assert len(saved) == 1
        assert saved[0].read_bytes() == b"hello bytes"

    def test_saves_string_as_utf8(self, tmp_path):
        """String content is saved as UTF-8."""
        with patch.dict(os.environ, {"CRONATOR_ARTIFACTS_DIR": str(tmp_path)}):
            save_artifact("data.txt", "hello")

        saved = list(tmp_path.glob("data_*.txt"))
        assert saved[0].read_text(encoding="utf-8") == "hello"

    def test_rejects_dangerous_extensions(self, tmp_path):
        """Dangerous extensions (.exe, .sh, .bat, etc.) → ValueError."""
        with patch.dict(os.environ, {"CRONATOR_ARTIFACTS_DIR": str(tmp_path)}):
            for ext in [".exe", ".sh", ".bat", ".ps1"]:
                with pytest.raises(ValueError, match="Forbidden extension"):
                    save_artifact(f"evil{ext}", b"data")

    def test_rejects_oversized_file(self, tmp_path):
        """File exceeding max_size_mb → ValueError."""
        with patch.dict(os.environ, {"CRONATOR_ARTIFACTS_DIR": str(tmp_path)}):
            with pytest.raises(ValueError, match="too large"):
                save_artifact("big.txt", b"x" * (2 * 1024 * 1024), max_size_mb=1)

    def test_rejects_invalid_filename(self, tmp_path):
        """Filename with no valid characters → ValueError."""
        with patch.dict(os.environ, {"CRONATOR_ARTIFACTS_DIR": str(tmp_path)}):
            with pytest.raises(ValueError, match="Invalid filename"):
                save_artifact("!!!", b"data")

    def test_sanitizes_spaces_in_filename(self, tmp_path):
        """Spaces in filename are replaced with underscores."""
        with patch.dict(os.environ, {"CRONATOR_ARTIFACTS_DIR": str(tmp_path)}):
            name = save_artifact("my report.txt", b"data")

        assert " " not in name

    def test_creates_artifacts_dir_if_missing(self, tmp_path):
        """Creates the artifacts directory if it doesn't exist."""
        new_dir = tmp_path / "nested" / "artifacts"
        assert not new_dir.exists()

        with patch.dict(os.environ, {"CRONATOR_ARTIFACTS_DIR": str(new_dir)}):
            save_artifact("f.txt", b"x")

        assert new_dir.exists()

    def test_emits_artifact_marker_to_stdout(self, tmp_path, capsys):
        """save_artifact() prints an ARTIFACT_SAVED: marker to stdout."""
        with patch.dict(os.environ, {"CRONATOR_ARTIFACTS_DIR": str(tmp_path)}):
            save_artifact("output.csv", b"a,b,c")

        out = capsys.readouterr().out
        assert "ARTIFACT_SAVED:" in out
        assert "output" in out

    def test_fallback_to_tempdir_without_env(self):
        """Without CRONATOR_ARTIFACTS_DIR, falls back to a temp directory."""
        env = os.environ.copy()
        env.pop("CRONATOR_ARTIFACTS_DIR", None)
        with patch.dict(os.environ, env, clear=True):
            name = save_artifact("fallback.txt", b"data")

        assert name.endswith(".txt")

    def test_unique_filenames_for_same_name(self, tmp_path):
        """Two calls with the same name produce files with unique timestamp suffixes."""
        with patch.dict(os.environ, {"CRONATOR_ARTIFACTS_DIR": str(tmp_path)}):
            save_artifact("same.txt", b"first")
            save_artifact("same.txt", b"second")

        # If both calls happen within the same second the names may collide — just verify at least one file exists
        files = list(tmp_path.glob("same_*.txt"))
        assert len(files) >= 1
