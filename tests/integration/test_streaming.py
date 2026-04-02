"""Integration tests for SSE streaming endpoint: GET /api/executions/{id}/stream."""

import asyncio
import json

import pytest
from httpx import AsyncClient

from app.models.execution import ExecutionStatus

# ─────────────────────────── SSE helpers ─────────────────────────────────────


def parse_sse(raw: bytes | str) -> list[dict]:
    """
    Разбивает SSE-текст на список событий.
    Каждое событие — dict с ключами 'event', 'data', 'comment' (любые из них могут отсутствовать).
    Блоки разделяются пустой строкой (\\n\\n).
    """
    text = raw.decode() if isinstance(raw, bytes) else raw
    events: list[dict] = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event: dict = {}
        for line in block.split("\n"):
            if line.startswith("event: "):
                event["event"] = line[7:]
            elif line.startswith("data:"):
                event["data"] = line[5:].lstrip(" ")
            elif line.startswith(":"):
                event["comment"] = line[1:].strip()
        if event:
            events.append(event)
    return events


# ─────────────────────────── tests ───────────────────────────────────────────


class TestStreamingSSE:
    """Интеграционные тесты SSE-стриминга логов выполнения скрипта."""

    # ── 404 / базовые ────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_stream_returns_404_for_unknown_execution(self, test_client: AsyncClient):
        """Стриминг несуществующего execution → 404."""
        response = await test_client.get("/api/executions/99999/stream")
        assert response.status_code == 404

    # ── stored-output path (завершённое выполнение, очереди нет) ─────────────

    @pytest.mark.asyncio
    async def test_stream_returns_200_with_sse_content_type(
        self, test_client: AsyncClient, execution_factory, sample_script
    ):
        """Стриминг завершённого execution → 200 text/event-stream."""
        execution = await execution_factory(
            script_id=sample_script.id,
            status=ExecutionStatus.SUCCESS.value,
            stdout="ok\n",
        )
        async with test_client.stream("GET", f"/api/executions/{execution.id}/stream") as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]
            await response.aread()

    @pytest.mark.asyncio
    async def test_stream_sse_no_cache_header(
        self, test_client: AsyncClient, execution_factory, sample_script
    ):
        """Стриминговый ответ содержит Cache-Control: no-cache."""
        execution = await execution_factory(
            script_id=sample_script.id,
            status=ExecutionStatus.SUCCESS.value,
            stdout="ok\n",
        )
        async with test_client.stream("GET", f"/api/executions/{execution.id}/stream") as response:
            assert response.headers.get("cache-control") == "no-cache"
            await response.aread()

    @pytest.mark.asyncio
    async def test_stream_stdout_lines_from_completed_execution(
        self, test_client: AsyncClient, execution_factory, sample_script
    ):
        """Стриминг завершённого execution → все строки stdout приходят как data-события."""
        execution = await execution_factory(
            script_id=sample_script.id,
            status=ExecutionStatus.SUCCESS.value,
            stdout="alpha\nbeta\ngamma\n",
            stderr="",
        )
        async with test_client.stream("GET", f"/api/executions/{execution.id}/stream") as response:
            raw = await response.aread()

        events = parse_sse(raw)
        data_lines = [e["data"] for e in events if e.get("event") == "stdout"]

        assert "alpha" in data_lines
        assert "beta" in data_lines
        assert "gamma" in data_lines

    @pytest.mark.asyncio
    async def test_stream_stderr_lines_from_failed_execution(
        self, test_client: AsyncClient, execution_factory, sample_script
    ):
        """Стриминг упавшего execution → stderr включён в поток."""
        execution = await execution_factory(
            script_id=sample_script.id,
            status=ExecutionStatus.FAILED.value,
            stdout="",
            stderr="Traceback:\n  ...\nRuntimeError: boom\n",
            exit_code=1,
        )
        async with test_client.stream("GET", f"/api/executions/{execution.id}/stream") as response:
            raw = await response.aread()

        events = parse_sse(raw)
        data_lines = [e["data"] for e in events if e.get("event") == "stderr"]
        assert any("RuntimeError: boom" in line for line in data_lines)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "status,stdout,stderr,exit_code",
        [
            (ExecutionStatus.SUCCESS.value, "hi\n", "", 0),
            (ExecutionStatus.FAILED.value, "", "error\n", 1),
        ],
        ids=["success", "failed"],
    )
    async def test_stream_done_event_status_and_exit_code(
        self,
        test_client: AsyncClient,
        execution_factory,
        sample_script,
        status,
        stdout,
        stderr,
        exit_code,
    ):
        """event: done содержит правильные status и exit_code для success и failed."""
        execution = await execution_factory(
            script_id=sample_script.id,
            status=status,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
        )
        async with test_client.stream("GET", f"/api/executions/{execution.id}/stream") as response:
            raw = await response.aread()

        events = parse_sse(raw)
        done_events = [e for e in events if e.get("event") == "done"]

        assert len(done_events) == 1
        payload = json.loads(done_events[0]["data"])
        assert payload["status"] == status
        assert payload["exit_code"] == exit_code

    @pytest.mark.asyncio
    async def test_stream_empty_execution_has_only_done_event(
        self, test_client: AsyncClient, execution_factory, sample_script
    ):
        """Execution без stdout/stderr → только event: done, никаких data-событий."""
        execution = await execution_factory(
            script_id=sample_script.id,
            status=ExecutionStatus.SUCCESS.value,
            stdout="",
            stderr="",
        )
        async with test_client.stream("GET", f"/api/executions/{execution.id}/stream") as response:
            raw = await response.aread()

        events = parse_sse(raw)
        data_events = [e for e in events if "data" in e and "event" not in e]
        done_events = [e for e in events if e.get("event") == "done"]

        assert data_events == []
        assert len(done_events) == 1

    @pytest.mark.asyncio
    async def test_stream_multiline_stdout_no_embedded_newlines_in_sse(
        self, test_client: AsyncClient, execution_factory, sample_script
    ):
        """
        SSE-протокол запрещает \\n внутри data: строки.
        Каждая строка stdout → отдельный data-блок.
        """
        execution = await execution_factory(
            script_id=sample_script.id,
            status=ExecutionStatus.SUCCESS.value,
            stdout="line_one\nline_two\nline_three\n",
        )
        async with test_client.stream("GET", f"/api/executions/{execution.id}/stream") as response:
            raw = await response.aread()

        text = raw.decode()
        # В SSE каждый data: payload не должен содержать \n
        for sse_line in text.split("\n"):
            if sse_line.startswith("data: "):
                assert "\n" not in sse_line[6:], (
                    f"SSE data line contains embedded newline: {sse_line!r}"
                )

    # ── live queue path (активное выполнение) ────────────────────────────────

    @pytest.mark.asyncio
    async def test_stream_live_execution_via_queue(
        self, test_client: AsyncClient, execution_factory, sample_script
    ):
        """
        Активное выполнение: данные читаются из asyncio.Queue.
        Заполняем очередь заранее — endpoint вычитывает и отдаёт SSE.
        """
        import app.api.executions as executions_module

        execution = await execution_factory(
            script_id=sample_script.id,
            status=ExecutionStatus.RUNNING.value,
            stdout="",
            stderr="",
        )

        queue: asyncio.Queue = asyncio.Queue()
        await queue.put(("stdout", "live_alpha\n"))
        await queue.put(("stdout", "live_beta\n"))
        await queue.put(("done", None))

        executions_module.executor_service.output_queues[execution.id] = queue

        try:
            async with test_client.stream(
                "GET", f"/api/executions/{execution.id}/stream"
            ) as response:
                assert response.status_code == 200
                raw = await response.aread()
        finally:
            executions_module.executor_service.output_queues.pop(execution.id, None)

        events = parse_sse(raw)
        data_lines = [e["data"] for e in events if e.get("event") == "stdout"]
        assert "live_alpha" in data_lines
        assert "live_beta" in data_lines

    @pytest.mark.asyncio
    async def test_stream_live_execution_x_accel_buffering_header(
        self, test_client: AsyncClient, execution_factory, sample_script
    ):
        """Активное выполнение (live queue) → X-Accel-Buffering: no (для nginx)."""
        import app.api.executions as executions_module

        execution = await execution_factory(
            script_id=sample_script.id,
            status=ExecutionStatus.RUNNING.value,
        )

        queue: asyncio.Queue = asyncio.Queue()
        await queue.put(("done", None))

        executions_module.executor_service.output_queues[execution.id] = queue

        try:
            async with test_client.stream(
                "GET", f"/api/executions/{execution.id}/stream"
            ) as response:
                assert response.headers.get("x-accel-buffering") == "no"
                await response.aread()
        finally:
            executions_module.executor_service.output_queues.pop(execution.id, None)
