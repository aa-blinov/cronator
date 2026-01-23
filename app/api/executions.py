"""API routes for executions."""

import asyncio
import json
from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.database import get_db
from app.models.execution import Execution, ExecutionStatus
from app.schemas.execution import ExecutionList, ExecutionRead, ExecutionStats
from app.services.executor import executor_service

router = APIRouter()


@router.get("", response_model=ExecutionList)
async def list_executions(
    page: int = 1,
    per_page: int = 50,
    script_id: int | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List executions with pagination and filtering."""
    query = select(Execution).options(joinedload(Execution.script))
    
    if script_id is not None:
        query = query.where(Execution.script_id == script_id)
    
    if status:
        query = query.where(Execution.status == status)
    
    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0
    
    # Paginate
    query = query.order_by(Execution.started_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    
    result = await db.execute(query)
    executions = result.scalars().all()
    
    items = []
    for exc in executions:
        data = ExecutionRead.model_validate(exc)
        data.duration_formatted = exc.duration_formatted
        data.script_name = exc.script.name if exc.script else None
        items.append(data)
    
    return ExecutionList(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        pages=(total + per_page - 1) // per_page,
    )


@router.get("/stats", response_model=ExecutionStats)
async def get_execution_stats(
    script_id: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Get execution statistics."""
    base_query = select(Execution)
    if script_id:
        base_query = base_query.where(Execution.script_id == script_id)
    
    # Total
    total_query = select(func.count()).select_from(base_query.subquery())
    total = await db.scalar(total_query) or 0
    
    # By status
    success_query = base_query.where(Execution.status == ExecutionStatus.SUCCESS.value)
    success = await db.scalar(select(func.count()).select_from(success_query.subquery())) or 0
    
    failed_query = base_query.where(
        Execution.status.in_([ExecutionStatus.FAILED.value, ExecutionStatus.TIMEOUT.value])
    )
    failed = await db.scalar(select(func.count()).select_from(failed_query.subquery())) or 0
    
    running_query = base_query.where(Execution.status == ExecutionStatus.RUNNING.value)
    running = await db.scalar(select(func.count()).select_from(running_query.subquery())) or 0
    
    # Success rate
    success_rate = (success / total * 100) if total > 0 else 0.0
    
    # Average duration
    avg_query = select(func.avg(Execution.duration_ms)).where(
        Execution.duration_ms.isnot(None)
    )
    if script_id:
        avg_query = avg_query.where(Execution.script_id == script_id)
    avg_duration = await db.scalar(avg_query)
    
    return ExecutionStats(
        total_executions=total,
        successful=success,
        failed=failed,
        running=running,
        success_rate=round(success_rate, 1),
        avg_duration_ms=avg_duration,
    )


@router.get("/{execution_id}", response_model=ExecutionRead)
async def get_execution(
    execution_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get execution details."""
    result = await db.execute(
        select(Execution)
        .options(joinedload(Execution.script))
        .where(Execution.id == execution_id)
    )
    execution = result.scalar_one_or_none()
    
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    
    data = ExecutionRead.model_validate(execution)
    data.duration_formatted = execution.duration_formatted
    data.script_name = execution.script.name if execution.script else None
    
    return data


@router.post("/{execution_id}/cancel")
async def cancel_execution(
    execution_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Cancel a running execution."""
    result = await db.execute(select(Execution).where(Execution.id == execution_id))
    execution = result.scalar_one_or_none()
    
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    
    if execution.status != ExecutionStatus.RUNNING.value:
        raise HTTPException(status_code=400, detail="Execution is not running")
    
    success = await executor_service.cancel_execution(execution_id)
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to cancel execution")
    
    return {"message": "Execution cancelled"}


@router.get("/{execution_id}/stream")
async def stream_execution_output(
    execution_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Stream execution output using Server-Sent Events."""
    # Check if execution exists
    result = await db.execute(select(Execution).where(Execution.id == execution_id))
    execution = result.scalar_one_or_none()
    
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    
    # Check if output queue exists
    if execution_id not in executor_service.output_queues:
        # Execution might have finished before streaming started
        # Return stored output
        async def send_stored_output():
            def iter_lines(text: str):
                # Preserve empty lines while avoiding trailing \r/\n in SSE payload
                for raw in text.splitlines(keepends=True):
                    yield raw.rstrip("\r\n")
                if text.endswith("\n"):
                    # splitlines(keepends=True) drops the final empty line after a trailing newline
                    yield ""

            for line in iter_lines(execution.stdout or ""):
                yield f"data: {line}\n\n"
            for line in iter_lines(execution.stderr or ""):
                yield f"data: {line}\n\n"

            done_payload = json.dumps({
                "status": execution.status,
                "exit_code": execution.exit_code,
            })
            yield f"event: done\ndata: {done_payload}\n\n"
        
        return StreamingResponse(
            send_stored_output(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )
    
    async def event_generator():
        """Generate SSE events from output queue."""
        queue = executor_service.output_queues[execution_id]
        last_activity = asyncio.get_event_loop().time()
        
        try:
            while True:
                try:
                    # Wait for output; periodically send keep-alive comments
                    stream_type, line = await asyncio.wait_for(
                        queue.get(),
                        timeout=15.0,
                    )
                    last_activity = asyncio.get_event_loop().time()
                    
                    if stream_type == "done":
                        # Refresh execution to get final status
                        await db.refresh(execution)
                        done_payload = json.dumps({
                            "status": execution.status,
                            "exit_code": execution.exit_code,
                        })
                        yield f"event: done\ndata: {done_payload}\n\n"
                        break

                    # IMPORTANT: do not embed newlines inside an SSE `data:` line.
                    # Send one log line per SSE message.
                    payload = (line or "").rstrip("\r\n")
                    yield f"data: {payload}\n\n"
                    
                except asyncio.TimeoutError:
                    # Keep-alive (comments are ignored by EventSource)
                    current_time = asyncio.get_event_loop().time()
                    if current_time - last_activity >= 15.0:
                        yield ": keep-alive\n\n"
                        last_activity = current_time
                    continue
                    
        finally:
            # Cleanup queue
            if execution_id in executor_service.output_queues:
                del executor_service.output_queues[execution_id]
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete("/{execution_id}")
async def delete_execution(
    execution_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete an execution record."""
    result = await db.execute(select(Execution).where(Execution.id == execution_id))
    execution = result.scalar_one_or_none()
    
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    
    if execution.status == ExecutionStatus.RUNNING.value:
        raise HTTPException(status_code=400, detail="Cannot delete running execution")
    
    await db.delete(execution)
    await db.commit()
    
    return {"message": "Execution deleted"}


@router.delete("")
async def clear_old_executions(
    days: int = 30,
    script_id: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Delete executions older than specified days."""
    from datetime import datetime, timedelta
    
    cutoff = datetime.now(UTC) - timedelta(days=days)
    
    query = select(Execution).where(
        Execution.started_at < cutoff,
        Execution.status != ExecutionStatus.RUNNING.value,
    )
    
    if script_id:
        query = query.where(Execution.script_id == script_id)
    
    result = await db.execute(query)
    executions = result.scalars().all()
    
    count = len(executions)
    for exc in executions:
        await db.delete(exc)
    
    await db.commit()
    
    return {"deleted": count, "message": f"Deleted {count} executions older than {days} days"}
