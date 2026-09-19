"""Every uv subprocess call in EnvironmentService (venv creation, pip
install, both plain and streaming) used to have no timeout at all —
process.communicate() or a readline()-based read loop that blocks until
EOF, i.e. until the process exits on its own. A stalled network call
(pip install hanging mid-download) would hang forever, and since
executor._run_script() calls setup_environment() *before* the script's
own process even starts, script.timeout never got a chance to apply
either. These tests pin down that every path is now bounded.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.environment import EnvironmentService


def _hanging_process(returncode: int = 0):
    """A process whose stdout/stderr never produce a line and never hit EOF."""
    never_resolves = asyncio.Event()

    async def _block_forever():
        await never_resolves.wait()
        return b""  # unreachable

    proc = MagicMock()
    proc.pid = 1234
    proc.returncode = None
    proc.stdout = AsyncMock()
    proc.stdout.readline = AsyncMock(side_effect=_block_forever)
    proc.stderr = AsyncMock()
    proc.stderr.readline = AsyncMock(side_effect=_block_forever)
    proc.kill = MagicMock()
    proc.wait = AsyncMock(return_value=-9)
    proc.communicate = AsyncMock(side_effect=_block_forever)
    return proc


@pytest.fixture
def service(tmp_path) -> EnvironmentService:
    svc = EnvironmentService()
    svc.install_timeout = 0.2  # keep the tests fast
    svc.envs_dir = tmp_path
    return svc


@pytest.mark.asyncio
async def test_create_env_times_out_instead_of_hanging(service):
    proc = _hanging_process()
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        ok, msg = await asyncio.wait_for(service.create_env("stalled_script"), timeout=5)

    assert ok is False
    assert "timed out" in msg.lower()
    proc.kill.assert_called_once()


@pytest.mark.asyncio
async def test_active_processes_tracked_while_running_and_cleared_after(service):
    """_active_processes (what graceful shutdown iterates to kill orphaned
    uv subprocesses) must contain the process while it runs and be cleared
    once it's done — whether it succeeded or hung and got killed."""
    ok_proc = MagicMock()
    ok_proc.pid = 1
    ok_proc.returncode = 0
    ok_proc.communicate = AsyncMock(return_value=(b"", b""))

    seen_during_run = []

    async def capture_and_communicate():
        seen_during_run.append(set(service._active_processes))
        return b"", b""

    ok_proc.communicate = AsyncMock(side_effect=capture_and_communicate)

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=ok_proc)):
        await service.create_env("tracked_script")

    assert seen_during_run == [{ok_proc}]
    assert service._active_processes == set()


@pytest.mark.asyncio
async def test_active_processes_cleared_after_a_timeout_kill(service):
    proc = _hanging_process()
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        await asyncio.wait_for(service.create_env("stalled_script"), timeout=5)

    assert service._active_processes == set()


@pytest.mark.asyncio
async def test_install_dependencies_times_out_instead_of_hanging(service):
    env_path = service.get_env_path("stalled_script")
    env_path.mkdir(parents=True)

    proc = _hanging_process()
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        ok, msg = await asyncio.wait_for(
            service.install_dependencies("stalled_script", "requests"), timeout=5
        )

    assert ok is False
    assert "timed out" in msg.lower()
    proc.kill.assert_called_once()


@pytest.mark.asyncio
async def test_streaming_install_retries_after_a_timed_out_attempt_then_succeeds(service):
    env_path = service.get_env_path("stalled_script")
    env_path.mkdir(parents=True)
    service.retry_config = {
        "max_attempts": 2,
        "base_delay": 0.01,
        "max_delay": 0.01,
        "backoff_factor": 1.0,
    }

    hung = _hanging_process()
    ok_proc = MagicMock()
    ok_proc.pid = 5678
    ok_proc.returncode = 0
    ok_proc.stdout = AsyncMock()
    ok_proc.stdout.readline = AsyncMock(return_value=b"")
    ok_proc.stderr = AsyncMock()
    ok_proc.stderr.readline = AsyncMock(return_value=b"")
    ok_proc.wait = AsyncMock(return_value=0)

    with patch(
        "asyncio.create_subprocess_exec",
        AsyncMock(side_effect=[hung, ok_proc]),
    ):
        ok, msg = await asyncio.wait_for(
            service._install_dependencies_streaming(1, "stalled_script", "requests"),
            timeout=5,
        )

    assert ok is True
    hung.kill.assert_called_once()


@pytest.mark.asyncio
async def test_streaming_install_cleans_up_queue_even_if_client_never_connects(service):
    """install_queues[script_id] used to be deleted only by the SSE endpoint's
    `finally` block, on the consumer side. If a client never opened the
    stream (closed tab, network error before connecting), the Queue — and
    every log line pushed to it — stayed in memory forever. The producer
    must clean up its own entry regardless of whether anyone was listening.
    """
    env_path = service.get_env_path("never_watched")
    env_path.mkdir(parents=True)

    ok_proc = MagicMock()
    ok_proc.pid = 999
    ok_proc.returncode = 0
    ok_proc.stdout = AsyncMock()
    ok_proc.stdout.readline = AsyncMock(return_value=b"")
    ok_proc.stderr = AsyncMock()
    ok_proc.stderr.readline = AsyncMock(return_value=b"")
    ok_proc.wait = AsyncMock(return_value=0)

    service.install_queues[1] = asyncio.Queue()  # nobody ever reads from this

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=ok_proc)):
        await asyncio.wait_for(
            service.setup_environment_streaming(1, "never_watched", "3.12", ""),
            timeout=5,
        )

    assert 1 not in service.install_queues


@pytest.mark.asyncio
async def test_streaming_install_fails_after_timeout_on_last_attempt(service):
    env_path = service.get_env_path("stalled_script")
    env_path.mkdir(parents=True)
    service.retry_config = {
        "max_attempts": 1,
        "base_delay": 0.01,
        "max_delay": 0.01,
        "backoff_factor": 1.0,
    }

    hung = _hanging_process()
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=hung)):
        ok, msg = await asyncio.wait_for(
            service._install_dependencies_streaming(1, "stalled_script", "requests"),
            timeout=5,
        )

    assert ok is False
    assert "timed out" in msg.lower()
