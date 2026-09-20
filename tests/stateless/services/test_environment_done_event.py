import asyncio
from unittest.mock import patch

import pytest

import app.main  # noqa: F401 - forces model/db import order before services
from app.services.environment import EnvironmentService


@pytest.mark.asyncio
async def test_done_event_reflects_real_failure():
    svc = EnvironmentService()
    svc.install_queues[999] = asyncio.Queue()

    queue = svc.install_queues[999]

    with patch.object(svc, "_create_env_streaming", return_value=(True, "ok")), \
         patch.object(svc, "_install_dependencies_streaming", return_value=(False, "pip install failed with code 1")):
        await svc.setup_environment_streaming(999, "fake-script", dependencies="requests")

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    done_events = [e for e in events if e[0] == "done"]
    assert done_events == [("done", "false")]

