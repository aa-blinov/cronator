"""Page routes for HTML templates."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.api.dependencies import verify_credentials
from app.config import get_settings
from app.database import get_db
from app.models.execution import Execution, ExecutionStatus
from app.models.script import Script
from app.models.script_version import ScriptVersion
from app.services.executor import executor_service
from app.services.scheduler import scheduler_service

router = APIRouter()
settings = get_settings()
security = HTTPBasic()


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    username: str = Depends(verify_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Dashboard page showing all scripts."""
    # Get scripts with their last execution
    result = await db.execute(select(Script).order_by(Script.name))
    scripts = result.scalars().all()

    # Enrich with execution info
    scripts_data = []
    for script in scripts:
        # Get last execution
        last_exec_result = await db.execute(
            select(Execution)
            .where(Execution.script_id == script.id)
            .order_by(Execution.started_at.desc())
            .limit(1)
        )
        last_exec = last_exec_result.scalar_one_or_none()

        scripts_data.append(
            {
                "script": script,
                "last_execution": last_exec,
                "next_run": scheduler_service.get_next_run_time(script.id),
            }
        )

    # Get stats
    total_scripts = len(scripts)
    enabled_scripts = sum(1 for s in scripts if s.enabled)

    # Recent executions stats
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    today_execs = (
        await db.scalar(
            select(func.count()).select_from(Execution).where(Execution.started_at >= today_start)
        )
        or 0
    )

    failed_today = (
        await db.scalar(
            select(func.count())
            .select_from(Execution)
            .where(
                Execution.started_at >= today_start,
                Execution.status.in_([ExecutionStatus.FAILED.value, ExecutionStatus.TIMEOUT.value]),
            )
        )
        or 0
    )

    running_now = (
        await db.scalar(
            select(func.count())
            .select_from(Execution)
            .where(Execution.status == ExecutionStatus.RUNNING.value)
        )
        or 0
    )

    return request.app.state.templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "page_title": "Dashboard",
            "scripts": scripts_data,
            "stats": {
                "total_scripts": total_scripts,
                "enabled_scripts": enabled_scripts,
                "today_executions": today_execs,
                "failed_today": failed_today,
                "running_now": running_now,
            },
            "now": datetime.now(UTC),
        },
    )


@router.get("/scripts/new", response_class=HTMLResponse)
async def script_new(
    request: Request,
    username: str = Depends(verify_credentials),
):
    """New script page."""
    return request.app.state.templates.TemplateResponse(
        "script_editor.html",
        {
            "request": request,
            "page_title": "New Script",
            "script": None,
            "content": (
                "#!/usr/bin/env python3\n"
                '"""New Cronator script."""\n\n'
                "from cronator_lib import get_logger\n\n"
                "log = get_logger()\n\n"
                "def main():\n"
                '    log.info("Script started")\n'
                "    # Your code here\n"
                '    log.info("Script finished")\n\n'
                'if __name__ == "__main__":\n'
                "    main()\n"
            ),
            "python_versions": ["3.9", "3.10", "3.11", "3.12", "3.13"],
        },
    )


@router.get("/scripts/{script_id}", response_class=HTMLResponse)
async def script_detail(
    request: Request,
    script_id: int,
    page: int = 1,
    username: str = Depends(verify_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Script detail page with execution history."""
    result = await db.execute(select(Script).where(Script.id == script_id))
    script = result.scalar_one_or_none()

    if not script:
        raise HTTPException(status_code=404, detail="Script not found")

    # Get executions with pagination
    per_page = 20
    total_execs = (
        await db.scalar(
            select(func.count()).select_from(Execution).where(Execution.script_id == script_id)
        )
        or 0
    )

    result = await db.execute(
        select(Execution)
        .where(Execution.script_id == script_id)
        .order_by(Execution.started_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    executions = result.scalars().all()

    # Stats
    success_count = (
        await db.scalar(
            select(func.count())
            .select_from(Execution)
            .where(
                Execution.script_id == script_id, Execution.status == ExecutionStatus.SUCCESS.value
            )
        )
        or 0
    )

    success_rate = (success_count / total_execs * 100) if total_execs > 0 else 0

    return request.app.state.templates.TemplateResponse(
        "script_detail.html",
        {
            "request": request,
            "page_title": script.name,
            "script": script,
            "executions": executions,
            "next_run": scheduler_service.get_next_run_time(script.id),
            "stats": {
                "total": total_execs,
                "success_rate": round(success_rate, 1),
            },
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total_execs,
                "pages": (total_execs + per_page - 1) // per_page,
            },
        },
    )


@router.get("/scripts/{script_id}/edit", response_class=HTMLResponse)
async def script_edit(
    request: Request,
    script_id: int,
    username: str = Depends(verify_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Script editor page."""
    result = await db.execute(select(Script).where(Script.id == script_id))
    script = result.scalar_one_or_none()

    if not script:
        raise HTTPException(status_code=404, detail="Script not found")

    # Try to read content from file if not stored in DB
    content = script.content
    if not content and script.path:
        try:
            from pathlib import Path

            script_path = Path(script.path)
            if script_path.exists():
                content = script_path.read_text()
        except Exception:
            content = "# Error reading script file"

    return request.app.state.templates.TemplateResponse(
        "script_editor.html",
        {
            "request": request,
            "page_title": f"Edit: {script.name}",
            "script": script,
            "content": content,
            "python_versions": ["3.9", "3.10", "3.11", "3.12", "3.13"],
        },
    )


@router.get("/scripts/{script_id}/versions/{version_number}", response_class=HTMLResponse)
async def script_version_detail(
    request: Request,
    script_id: int,
    version_number: int,
    username: str = Depends(verify_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Script version detail page."""
    # Get script
    result = await db.execute(select(Script).where(Script.id == script_id))
    script = result.scalar_one_or_none()

    if not script:
        raise HTTPException(status_code=404, detail="Script not found")

    # Get version
    version_result = await db.execute(
        select(ScriptVersion).where(
            ScriptVersion.script_id == script_id,
            ScriptVersion.version_number == version_number,
        )
    )
    version = version_result.scalar_one_or_none()

    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    return request.app.state.templates.TemplateResponse(
        "script_version.html",
        {
            "request": request,
            "page_title": f"{script.name} - Version {version_number}",
            "script": script,
            "version": version,
        },
    )


@router.get("/executions", response_class=HTMLResponse)
async def executions_list(
    request: Request,
    page: int = 1,
    script_id: int | None = None,
    status_filter: str | None = None,
    username: str = Depends(verify_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Executions list page."""
    per_page = 50

    query = select(Execution).options(joinedload(Execution.script))

    if script_id:
        query = query.where(Execution.script_id == script_id)
    if status_filter:
        query = query.where(Execution.status == status_filter)

    # Count
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0

    # Paginate
    query = query.order_by(Execution.started_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)

    result = await db.execute(query)
    executions = result.scalars().all()

    # Get scripts for filter dropdown
    scripts_result = await db.execute(select(Script).order_by(Script.name))
    scripts = scripts_result.scalars().all()

    return request.app.state.templates.TemplateResponse(
        "executions.html",
        {
            "request": request,
            "page_title": "Executions",
            "executions": executions,
            "scripts": scripts,
            "filters": {
                "script_id": script_id,
                "status": status_filter,
            },
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "pages": (total + per_page - 1) // per_page,
            },
            "statuses": [s.value for s in ExecutionStatus],
        },
    )


@router.get("/executions/{execution_id}", response_class=HTMLResponse)
async def execution_detail(
    request: Request,
    execution_id: int,
    username: str = Depends(verify_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Execution detail page with full logs."""
    result = await db.execute(
        select(Execution).options(joinedload(Execution.script)).where(Execution.id == execution_id)
    )
    execution = result.scalar_one_or_none()

    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")

    return request.app.state.templates.TemplateResponse(
        "execution_detail.html",
        {
            "request": request,
            "page_title": f"Execution #{execution_id}",
            "execution": execution,
        },
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    username: str = Depends(verify_credentials),
):
    """Settings page."""
    return request.app.state.templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "page_title": "Settings",
            "settings": settings,
            "scheduler_jobs": scheduler_service.get_all_jobs_info(),
        },
    )


# Form actions


@router.post("/scripts/{script_id}/run")
async def run_script_action(
    script_id: int,
    username: str = Depends(verify_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Run a script manually."""
    result = await db.execute(select(Script).where(Script.id == script_id))
    script = result.scalar_one_or_none()

    if not script:
        raise HTTPException(status_code=404, detail="Script not found")

    execution_id = await executor_service.execute_script(script_id, triggered_by="manual")

    return RedirectResponse(
        url=f"/executions/{execution_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/scripts/{script_id}/toggle")
async def toggle_script_action(
    script_id: int,
    username: str = Depends(verify_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Toggle script enabled/disabled."""
    result = await db.execute(select(Script).where(Script.id == script_id))
    script = result.scalar_one_or_none()

    if not script:
        raise HTTPException(status_code=404, detail="Script not found")

    script.enabled = not script.enabled
    await db.commit()
    await scheduler_service.update_job(script)

    return RedirectResponse(
        url=f"/scripts/{script_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
