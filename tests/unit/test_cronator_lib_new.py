"""Unit tests for cronator_lib: CronatorContext, timer(), notify()."""

import json
import os
import time
from unittest.mock import MagicMock, patch

import pytest

from cronator_lib.context import get_context
from cronator_lib.notify import notify
from cronator_lib.timer import timer

# ─────────────────────────── CronatorContext ─────────────────────────────────


class TestCronatorContext:

    def test_is_cronator_true_when_execution_id_set(self):
        """CRONATOR_EXECUTION_ID set → is_cronator=True."""
        with patch.dict(os.environ, {"CRONATOR_EXECUTION_ID": "42"}):
            ctx = get_context()
        assert ctx.is_cronator is True

    def test_is_cronator_false_without_execution_id(self):
        """No CRONATOR_EXECUTION_ID → is_cronator=False."""
        env = {k: v for k, v in os.environ.items() if k != "CRONATOR_EXECUTION_ID"}
        with patch.dict(os.environ, env, clear=True):
            ctx = get_context()
        assert ctx.is_cronator is False

    def test_execution_id_parsed_as_int(self):
        """execution_id is read from env as int."""
        with patch.dict(os.environ, {"CRONATOR_EXECUTION_ID": "99"}):
            ctx = get_context()
        assert ctx.execution_id == 99
        assert isinstance(ctx.execution_id, int)

    def test_script_id_parsed_as_int(self):
        """script_id is read from env as int."""
        with patch.dict(os.environ, {"CRONATOR_SCRIPT_ID": "7"}):
            ctx = get_context()
        assert ctx.script_id == 7

    def test_execution_id_none_when_not_set(self):
        """execution_id is None when the env var is not set."""
        env = {k: v for k, v in os.environ.items() if k != "CRONATOR_EXECUTION_ID"}
        with patch.dict(os.environ, env, clear=True):
            ctx = get_context()
        assert ctx.execution_id is None

    def test_script_id_none_when_not_set(self):
        """script_id is None when the env var is not set."""
        env = {k: v for k, v in os.environ.items() if k != "CRONATOR_SCRIPT_ID"}
        with patch.dict(os.environ, env, clear=True):
            ctx = get_context()
        assert ctx.script_id is None

    def test_script_name_from_env(self):
        """script_name is read from CRONATOR_SCRIPT_NAME."""
        with patch.dict(os.environ, {"CRONATOR_SCRIPT_NAME": "my_report"}):
            ctx = get_context()
        assert ctx.script_name == "my_report"

    def test_script_name_empty_when_not_set(self):
        """script_name is an empty string when the env var is not set."""
        env = {k: v for k, v in os.environ.items() if k != "CRONATOR_SCRIPT_NAME"}
        with patch.dict(os.environ, env, clear=True):
            ctx = get_context()
        assert ctx.script_name == ""

    def test_artifacts_dir_as_path(self):
        """artifacts_dir is returned as a Path object."""
        from pathlib import Path
        with patch.dict(os.environ, {"CRONATOR_ARTIFACTS_DIR": "/tmp/artifacts"}):
            ctx = get_context()
        assert ctx.artifacts_dir == Path("/tmp/artifacts")

    def test_artifacts_dir_none_when_not_set(self):
        """artifacts_dir is None when the env var is not set."""
        env = {k: v for k, v in os.environ.items() if k != "CRONATOR_ARTIFACTS_DIR"}
        with patch.dict(os.environ, env, clear=True):
            ctx = get_context()
        assert ctx.artifacts_dir is None

    def test_context_is_frozen(self):
        """CronatorContext is immutable — fields cannot be reassigned."""
        with patch.dict(os.environ, {"CRONATOR_EXECUTION_ID": "1"}):
            ctx = get_context()
        with pytest.raises((AttributeError, TypeError)):
            ctx.execution_id = 999  # type: ignore[misc]

    def test_all_fields_populated_in_cronator_env(self):
        """All fields are populated when the full set of env vars is present."""
        env = {
            "CRONATOR_EXECUTION_ID": "10",
            "CRONATOR_SCRIPT_ID": "5",
            "CRONATOR_SCRIPT_NAME": "full_script",
            "CRONATOR_ARTIFACTS_DIR": "/data/artifacts",
        }
        with patch.dict(os.environ, env):
            ctx = get_context()

        assert ctx.execution_id == 10
        assert ctx.script_id == 5
        assert ctx.script_name == "full_script"
        assert ctx.artifacts_dir is not None
        assert ctx.is_cronator is True


# ─────────────────────────── timer ───────────────────────────────────────────


class TestTimer:

    def test_logs_completion_message(self):
        """timer() logs a completion message."""
        mock_logger = MagicMock()
        with timer("test block", logger=mock_logger):
            pass
        mock_logger.info.assert_called_once()
        msg = mock_logger.info.call_args[0][0]
        assert "test block" in msg
        assert "completed" in msg

    def test_elapsed_populated_after_exit(self):
        """After the context exits, elapsed contains real measured time."""
        mock_logger = MagicMock()
        with timer("t", logger=mock_logger) as t:
            time.sleep(0.05)
        assert t["elapsed"] >= 0.05

    def test_elapsed_zero_before_exit(self):
        """Inside the block, elapsed is still 0."""
        mock_logger = MagicMock()
        inside_value = None
        with timer("t", logger=mock_logger) as t:
            inside_value = t["elapsed"]
        assert inside_value == 0.0

    def test_formats_milliseconds(self):
        """Fast operations (<1 s) are formatted in ms."""
        mock_logger = MagicMock()
        with timer("fast", logger=mock_logger):
            pass
        msg = mock_logger.info.call_args[0][0]
        assert "ms" in msg

    def test_formats_seconds(self):
        """Operations taking 1–60 s are formatted in seconds."""
        mock_logger = MagicMock()
        with patch("time.perf_counter", side_effect=[0.0, 5.5]):
            with timer("slow", logger=mock_logger):
                pass
        msg = mock_logger.info.call_args[0][0]
        assert "s" in msg
        assert "ms" not in msg

    def test_formats_minutes(self):
        """Operations taking >60 s are formatted in minutes."""
        mock_logger = MagicMock()
        with patch("time.perf_counter", side_effect=[0.0, 125.0]):
            with timer("very slow", logger=mock_logger):
                pass
        msg = mock_logger.info.call_args[0][0]
        assert "m" in msg

    def test_label_included_in_message(self):
        """The label is included in the log message."""
        mock_logger = MagicMock()
        with timer("my_label", logger=mock_logger):
            pass
        msg = mock_logger.info.call_args[0][0]
        assert "my_label" in msg

    def test_no_label_still_logs(self):
        """Without a label, timer still logs (no [] prefix)."""
        mock_logger = MagicMock()
        with timer(logger=mock_logger):
            pass
        mock_logger.info.assert_called_once()

    def test_uses_get_logger_in_local_mode(self):
        """Without CRONATOR_EXECUTION_ID, uses get_logger()."""
        mock_logger = MagicMock()
        env = {k: v for k, v in os.environ.items() if k != "CRONATOR_EXECUTION_ID"}
        with patch.dict(os.environ, env, clear=True):
            with patch("cronator_lib.timer.get_logger", return_value=mock_logger):
                with timer("auto"):
                    pass
        mock_logger.info.assert_called_once()

    def test_emits_json_with_timer_level_in_cronator_context(self, capsys):
        """In Cronator context, prints JSON with level=TIMER to stdout."""
        with patch.dict(os.environ, {"CRONATOR_EXECUTION_ID": "1"}):
            with timer("db query"):
                pass
        out = capsys.readouterr().out
        parsed = json.loads(out.strip())
        assert parsed["level"] == "TIMER"
        assert "db query" in parsed["message"]

    def test_timer_json_preserves_unicode_characters(self, capsys):
        """Timer JSON should keep non-ASCII characters readable in raw stdout."""
        with patch.dict(os.environ, {"CRONATOR_EXECUTION_ID": "1"}):
            with timer("data load"):
                pass
        out = capsys.readouterr().out
        parsed = json.loads(out.strip())
        assert "data load" in parsed["message"]

    def test_logs_even_on_exception(self):
        """Elapsed time is logged even when the block raises an exception."""
        mock_logger = MagicMock()
        with pytest.raises(ValueError):
            with timer("failing", logger=mock_logger):
                raise ValueError("oops")
        mock_logger.info.assert_called_once()

    def test_exception_propagates(self):
        """Exceptions raised inside the block propagate normally."""
        mock_logger = MagicMock()
        with pytest.raises(RuntimeError, match="boom"):
            with timer("t", logger=mock_logger):
                raise RuntimeError("boom")


# ─────────────────────────── notify ──────────────────────────────────────────


class TestNotify:

    def test_prints_cronator_notify_marker(self, capsys):
        """notify() prints a CRONATOR_NOTIFY: marker to stdout."""
        notify("all done")
        out = capsys.readouterr().out
        assert "CRONATOR_NOTIFY:" in out

    def test_message_present_in_output(self, capsys):
        """The message text is present in the output."""
        notify("export done: 500 rows")
        out = capsys.readouterr().out
        assert "export done: 500 rows" in out

    def test_without_explicit_title_no_pipe_in_payload(self, capsys):
        """Without an explicit title, the payload does not contain | (message only)."""
        notify("hello")
        out = capsys.readouterr().out
        marker_idx = out.find("CRONATOR_NOTIFY:")
        payload = out[marker_idx + len("CRONATOR_NOTIFY:"):].strip()
        assert "|" not in payload
        assert payload == "hello"

    def test_custom_title_used_when_provided(self, capsys):
        """A custom title is included in the output."""
        notify("disk 90%", title="Warning")
        out = capsys.readouterr().out
        assert "Warning" in out

    def test_title_and_message_separated_by_pipe(self, capsys):
        """title and message are separated by | for executor parsing."""
        notify("body text", title="MyTitle")
        out = capsys.readouterr().out
        marker_idx = out.find("CRONATOR_NOTIFY:")
        payload = out[marker_idx + len("CRONATOR_NOTIFY:"):].strip()
        assert "|" in payload
        title_part, body_part = payload.split("|", 1)
        assert title_part.strip() == "MyTitle"
        assert body_part.strip() == "body text"

    def test_nothing_goes_to_stderr(self, capsys):
        """notify() writes nothing to stderr."""
        notify("test")
        err = capsys.readouterr().err
        assert err == ""

    def test_output_is_flushed(self, capsys):
        """stdout is flushed (flush=True) to ensure the marker reaches the executor."""
        stdout_mock = MagicMock()
        stdout_mock.write = MagicMock()
        stdout_mock.flush = MagicMock()
        with patch("builtins.print") as mock_print:
            notify("flush test")
            mock_print.assert_called_once()
            _, kwargs = mock_print.call_args
            assert kwargs.get("flush") is True

    def test_without_script_name_env_message_still_sent(self, capsys):
        """Without CRONATOR_SCRIPT_NAME, the message is still sent."""
        env = {k: v for k, v in os.environ.items() if k != "CRONATOR_SCRIPT_NAME"}
        with patch.dict(os.environ, env, clear=True):
            notify("msg")
        out = capsys.readouterr().out
        assert "CRONATOR_NOTIFY:msg" in out
