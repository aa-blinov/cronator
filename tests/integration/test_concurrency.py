"""
Integration tests for ExecutorService concurrency — реальная БД, без subprocess.

Проверяем:
  - что запись Execution создаётся в БД при запуске
  - что второй вызов для того же скрипта → ValueError пока первый ещё «работает»
  - что разные скрипты запускаются параллельно без конфликта
  - что после завершения скрипт можно перезапустить (новая запись в БД)
  - что начальный статус Execution = RUNNING
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import Execution, ExecutionStatus
from app.models.script import Script
from app.services.executor import ExecutorService


# ─────────────────────────── tests ───────────────────────────────────────────


class TestConcurrencyIntegration:
    """Интеграционные тесты блокировки повторного запуска скрипта."""

    @pytest.mark.asyncio
    async def test_execute_script_creates_execution_in_db(
        self,
        exec_service: ExecutorService,
        db_script: Script,
        db_session: AsyncSession,
    ):
        """execute_script() создаёт запись Execution в БД с правильным script_id."""
        script_id = db_script.id  # сохраняем до expire
        with patch.object(exec_service, "_run_script", new=AsyncMock()):
            eid = await exec_service.execute_script(script_id)

        assert eid is not None
        # rollback завершает текущую транзакцию → новая видит коммит exec_service
        await db_session.rollback()
        execution = await db_session.get(Execution, eid)
        assert execution is not None
        assert execution.script_id == script_id

    @pytest.mark.asyncio
    async def test_execution_status_is_running_initially(
        self,
        exec_service: ExecutorService,
        db_script: Script,
        db_session: AsyncSession,
    ):
        """Сразу после запуска статус Execution = RUNNING."""
        script_id = db_script.id
        with patch.object(exec_service, "_run_script", new=AsyncMock()):
            eid = await exec_service.execute_script(script_id)

        await db_session.rollback()
        execution = await db_session.get(Execution, eid)
        assert execution.status == ExecutionStatus.RUNNING.value

    @pytest.mark.asyncio
    async def test_second_call_same_script_raises(
        self,
        exec_service: ExecutorService,
        db_script: Script,
    ):
        """Второй вызов execute_script для того же скрипта → ValueError."""
        with patch.object(exec_service, "_run_script", new=AsyncMock()):
            await exec_service.execute_script(db_script.id)

        with pytest.raises(ValueError, match="already running"):
            with patch.object(exec_service, "_run_script", new=AsyncMock()):
                await exec_service.execute_script(db_script.id)

    @pytest.mark.asyncio
    async def test_concurrent_different_scripts_both_succeed(
        self,
        exec_service: ExecutorService,
        db_session: AsyncSession,
    ):
        """Два разных скрипта запускаются параллельно — оба получают Execution в БД."""
        script_a = Script(
            name="conc_int_a",
            content="print('a')",
            cron_expression="0 * * * *",
            enabled=True,
            python_version="3.12",
            timeout=3600,
            path="/scripts/conc_int_a/main.py",
        )
        script_b = Script(
            name="conc_int_b",
            content="print('b')",
            cron_expression="0 * * * *",
            enabled=True,
            python_version="3.12",
            timeout=3600,
            path="/scripts/conc_int_b/main.py",
        )
        db_session.add_all([script_a, script_b])
        await db_session.commit()
        await db_session.refresh(script_a)
        await db_session.refresh(script_b)

        sid_a, sid_b = script_a.id, script_b.id  # сохраняем до expire

        with patch.object(exec_service, "_run_script", new=AsyncMock()):
            id_a, id_b = await asyncio.gather(
                exec_service.execute_script(sid_a),
                exec_service.execute_script(sid_b),
            )

        assert id_a is not None
        assert id_b is not None
        assert id_a != id_b

        await db_session.rollback()
        exec_a = await db_session.get(Execution, id_a)
        exec_b = await db_session.get(Execution, id_b)
        assert exec_a.script_id == sid_a
        assert exec_b.script_id == sid_b

    @pytest.mark.asyncio
    async def test_script_can_rerun_after_completion(
        self,
        exec_service: ExecutorService,
        db_script: Script,
        db_session: AsyncSession,
    ):
        """После удаления из _running_scripts скрипт запускается повторно — создаётся новая Execution."""
        script_id = db_script.id

        with patch.object(exec_service, "_run_script", new=AsyncMock()):
            eid1 = await exec_service.execute_script(script_id)

        exec_service._running_scripts.discard(script_id)

        with patch.object(exec_service, "_run_script", new=AsyncMock()):
            eid2 = await exec_service.execute_script(script_id)

        assert eid1 != eid2

        await db_session.rollback()
        result = await db_session.execute(
            select(Execution).where(Execution.script_id == script_id)
        )
        executions = result.scalars().all()
        assert len(executions) == 2

    @pytest.mark.asyncio
    async def test_script_not_found_raises_and_cleans_running_set(
        self,
        exec_service: ExecutorService,
    ):
        """Если скрипт не найден в БД — исключение, script_id убран из _running_scripts."""
        non_existent_id = 99999

        with pytest.raises(ValueError, match="not found"):
            await exec_service.execute_script(non_existent_id)

        # После ошибки скрипт не должен «зависнуть» как запущенный
        assert not exec_service.is_script_running(non_existent_id)
