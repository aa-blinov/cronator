"""API routes for scripts."""

import asyncio
import json
import logging

import aiofiles
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.rate_limit import rate_limit
from app.config import get_settings
from app.database import get_db
from app.models.execution import Execution
from app.models.script import Script
from app.schemas.script import (
    ScriptCreate,
    ScriptList,
    ScriptRead,
    ScriptReadWithInstallStatus,
    ScriptUpdate,
)
from app.services.environment import environment_service
from app.services.executor import executor_service
from app.services.scheduler import scheduler_service

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()


@router.get("", response_model=ScriptList)
async def list_scripts(
    page: int = 1,
    per_page: int = 20,
    enabled: bool | None = None,
    search: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List all scripts with pagination."""
    query = select(Script)

    if enabled is not None:
        query = query.where(Script.enabled == enabled)

    if search:
        query = query.where(Script.name.ilike(f"%{search}%"))

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0

    # Paginate
    query = query.order_by(Script.name).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    scripts = result.scalars().all()

    # Enrich with last run info and next run time
    items = []
    for script in scripts:
        script_data = ScriptRead.model_validate(script)

        # Get last execution
        last_exec_query = (
            select(Execution)
            .where(Execution.script_id == script.id)
            .order_by(Execution.started_at.desc())
            .limit(1)
        )
        last_exec_result = await db.execute(last_exec_query)
        last_exec = last_exec_result.scalar_one_or_none()

        if last_exec:
            script_data.last_run_status = last_exec.status
            script_data.last_run_at = last_exec.started_at

        # Get next run time
        script_data.next_run_at = scheduler_service.get_next_run_time(script.id)

        items.append(script_data)

    return ScriptList(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        pages=(total + per_page - 1) // per_page,
    )


@router.get("/{script_id}", response_model=ScriptRead)
async def get_script(
    script_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a script by ID."""
    result = await db.execute(select(Script).where(Script.id == script_id))
    script = result.scalar_one_or_none()

    if not script:
        raise HTTPException(status_code=404, detail="Script not found")

    script_data = ScriptRead.model_validate(script)

    # Get last execution
    last_exec_query = (
        select(Execution)
        .where(Execution.script_id == script.id)
        .order_by(Execution.started_at.desc())
        .limit(1)
    )
    last_exec_result = await db.execute(last_exec_query)
    last_exec = last_exec_result.scalar_one_or_none()

    if last_exec:
        script_data.last_run_status = last_exec.status
        script_data.last_run_at = last_exec.started_at

    script_data.next_run_at = scheduler_service.get_next_run_time(script.id)
    script_data.last_alert_at = script.last_alert_at
    script_data.is_managed_by_git = script.is_managed_by_git

    return script_data


@router.post("", response_model=ScriptReadWithInstallStatus, status_code=status.HTTP_201_CREATED)
async def create_script(
    data: ScriptCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new script."""
    # Check if name already exists
    existing = await db.execute(select(Script).where(Script.name == data.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Script with this name already exists")

    # Validate dependencies if provided
    if data.dependencies:
        is_valid, error_msg, _ = await environment_service.validate_dependencies(data.dependencies)
        if not is_valid:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid dependencies: {error_msg}",
            )

    # Determine script path
    if data.path:
        path = data.path
    else:
        # Create script in scripts directory
        script_dir = settings.scripts_dir / data.name
        script_dir.mkdir(parents=True, exist_ok=True)
        script_file = script_dir / "script.py"

        # Save relative path (without scripts_dir prefix)
        path = f"{data.name}/script.py"

        # Write script content
        async with aiofiles.open(script_file, "w") as f:
            await f.write(data.content or "# New script\nprint('Hello from Cronator!')\n")

    script = Script(
        name=data.name,
        description=data.description,
        path=path,
        content=data.content,
        cron_expression=data.cron_expression,
        enabled=data.enabled,
        python_version=data.python_version,
        dependencies=data.dependencies,
        alert_on_failure=data.alert_on_failure,
        alert_on_success=data.alert_on_success,
        timeout=data.timeout,
        working_directory=data.working_directory,
        environment_vars=data.environment_vars,
    )

    db.add(script)
    await db.commit()
    await db.refresh(script)

    # NOTE: Environment setup is now done separately via /scripts/{id}/install
    # to allow streaming of installation logs

    # Add to scheduler
    if script.enabled:
        await scheduler_service.add_job(script)

    # Build response with installation status
    return ScriptReadWithInstallStatus(
        **ScriptRead.model_validate(script).model_dump(),
        needs_install=bool(data.dependencies),
    )


@router.put("/{script_id}", response_model=ScriptReadWithInstallStatus)
async def update_script(
    script_id: int,
    data: ScriptUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a script."""
    result = await db.execute(select(Script).where(Script.id == script_id))
    script = result.scalar_one_or_none()

    if not script:
        raise HTTPException(status_code=404, detail="Script not found")

    # Check if name already exists (when renaming)
    if data.name is not None and data.name != script.name:
        existing = await db.execute(select(Script).where(Script.name == data.name))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Script with this name already exists")

    # Validate dependencies if provided
    if data.dependencies is not None:
        is_valid, error_msg, _ = await environment_service.validate_dependencies(data.dependencies)
        if not is_valid:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid dependencies: {error_msg}",
            )

    # Track what changed for environment/scheduler updates
    deps_changed = False
    python_changed = False
    schedule_changed = False
    enabled_changed = False

    update_data = data.model_dump(exclude_unset=True)

    # Update fields
    for field, value in update_data.items():
        if field == "dependencies":
            # Normalize empty strings and None for comparison
            old_deps = (script.dependencies or "").strip()
            new_deps = (value or "").strip()
            if new_deps != old_deps:
                deps_changed = True
        if field == "python_version" and value != script.python_version:
            python_changed = True
        if field == "cron_expression" and value != script.cron_expression:
            schedule_changed = True
        if field == "enabled" and value != script.enabled:
            enabled_changed = True

        setattr(script, field, value)

    needs_install = deps_changed or python_changed

    # Update script file if content changed
    if data.content is not None:
        script_path = settings.scripts_dir / script.name / "script.py"
        script_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(script_path, "w") as f:
            await f.write(data.content)
        # Save relative path (without scripts_dir prefix)
        script.path = f"{script.name}/script.py"

    await db.commit()
    await db.refresh(script)

    # NOTE: Environment setup is now done separately via /scripts/{id}/install
    # to allow streaming of installation logs

    # Update scheduler
    if schedule_changed or enabled_changed:
        await scheduler_service.update_job(script)

    # Build response with installation status
    return ScriptReadWithInstallStatus(
        **ScriptRead.model_validate(script).model_dump(),
        needs_install=needs_install,
    )


@router.delete("/{script_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_script(
    script_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a script."""
    result = await db.execute(select(Script).where(Script.id == script_id))
    script = result.scalar_one_or_none()

    if not script:
        raise HTTPException(status_code=404, detail="Script not found")

    # Remove from scheduler
    await scheduler_service.remove_job(script_id)

    # Delete environment
    await environment_service.delete_env(script.name)

    # Delete script
    await db.delete(script)
    await db.commit()


@router.post("/{script_id}/run")
@rate_limit(max_calls=5, period=60)  # Max 5 runs per minute
async def run_script(
    script_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger a script execution."""
    result = await db.execute(select(Script).where(Script.id == script_id))
    script = result.scalar_one_or_none()

    if not script:
        raise HTTPException(status_code=404, detail="Script not found")

    execution_id = await executor_service.execute_script(script_id, triggered_by="manual")

    return {"execution_id": execution_id, "message": "Script execution started"}


@router.post("/{script_id}/test")
@rate_limit(max_calls=10, period=60)  # Max 10 tests per minute
async def test_script(
    script_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Run a test execution (marked as test in database)."""
    result = await db.execute(select(Script).where(Script.id == script_id))
    script = result.scalar_one_or_none()

    if not script:
        raise HTTPException(status_code=404, detail="Script not found")

    # Check if script is already running
    if executor_service.is_script_running(script_id):
        raise HTTPException(status_code=409, detail="Script is already running")

    # Create execution with is_test=True
    execution_id = await executor_service.execute_script(
        script_id, triggered_by="test", is_test=True
    )

    return {"execution_id": execution_id, "message": "Test execution started"}


@router.post("/{script_id}/toggle")
async def toggle_script(
    script_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Toggle script enabled/disabled."""
    result = await db.execute(select(Script).where(Script.id == script_id))
    script = result.scalar_one_or_none()

    if not script:
        raise HTTPException(status_code=404, detail="Script not found")

    script.enabled = not script.enabled
    await db.commit()

    # Update scheduler
    await scheduler_service.update_job(script)

    return {"enabled": script.enabled}


@router.post("/{script_id}/rebuild-env")
@rate_limit(max_calls=3, period=60)  # Max 3 rebuilds per minute (expensive operation)
async def rebuild_environment(
    script_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Rebuild the script's virtual environment."""
    result = await db.execute(select(Script).where(Script.id == script_id))
    script = result.scalar_one_or_none()

    if not script:
        raise HTTPException(status_code=404, detail="Script not found")

    success, message = await environment_service.setup_environment(
        script.name,
        script.python_version,
        script.dependencies,
    )

    if not success:
        raise HTTPException(status_code=500, detail=message)

    return {"message": message}


@router.post("/{script_id}/install")
async def start_install(
    script_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Start environment setup in background with streaming support."""
    result = await db.execute(select(Script).where(Script.id == script_id))
    script = result.scalar_one_or_none()

    if not script:
        raise HTTPException(status_code=404, detail="Script not found")

    if environment_service.is_installing(script_id):
        raise HTTPException(status_code=409, detail="Installation already in progress")

    # Create queue for streaming
    environment_service.install_queues[script_id] = asyncio.Queue()

    # Start installation in background
    background_tasks.add_task(
        environment_service.setup_environment_streaming,
        script_id,
        script.name,
        script.python_version,
        script.dependencies or "",
    )

    return {"message": "Installation started", "script_id": script_id}


@router.get("/{script_id}/install-stream")
async def install_stream(
    script_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Stream installation logs via SSE."""
    result = await db.execute(select(Script).where(Script.id == script_id))
    script = result.scalar_one_or_none()

    if not script:
        raise HTTPException(status_code=404, detail="Script not found")

    queue = environment_service.install_queues.get(script_id)
    if not queue:
        # No active installation, return immediately
        async def no_install():
            yield 'event: error\ndata: {"message": "No installation in progress"}\n\n'

        return StreamingResponse(
            no_install(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    async def event_generator():
        """Generate SSE events from install queue."""
        try:
            while True:
                try:
                    event_type, message = await asyncio.wait_for(
                        queue.get(),
                        timeout=60.0,
                    )

                    if event_type == "done":
                        done_payload = json.dumps({"success": True})
                        yield f"event: done\ndata: {done_payload}\n\n"
                        break
                    elif event_type == "error":
                        yield f"data: {message}\n\n"
                    else:
                        yield f"data: {message}\n\n"

                except TimeoutError:
                    # Keep-alive
                    yield ": keep-alive\n\n"
                    continue

        finally:
            # Cleanup queue
            if script_id in environment_service.install_queues:
                del environment_service.install_queues[script_id]

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{script_id}/packages")
async def get_script_packages(
    script_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get list of installed packages in the script's virtual environment."""
    result = await db.execute(select(Script).where(Script.id == script_id))
    script = result.scalar_one_or_none()

    if not script:
        raise HTTPException(status_code=404, detail="Script not found")

    packages = await environment_service.get_installed_packages(script.name)
    return {"packages": packages}


@router.post("/validate-dependencies")
async def validate_dependencies(
    dependencies: dict,
):
    """Validate dependencies format and resolvability."""
    deps_string = dependencies.get("dependencies", "")

    if not deps_string:
        return {
            "valid": True,
            "message": "No dependencies to validate",
            "packages": [],
        }

    is_valid, error_msg, packages = await environment_service.validate_dependencies(deps_string)

    return {
        "valid": is_valid,
        "message": error_msg if not is_valid else "Dependencies are valid",
        "packages": packages,
    }


@router.post("/validate-script")
async def validate_script(
    data: dict,
):
    """Validate Python script syntax and code quality using Ruff."""
    import ast
    import asyncio
    import json
    import tempfile
    from pathlib import Path

    code = data.get("code", "")

    if not code.strip():
        return {
            "valid": True,
            "errors": [],
            "message": "No code to validate",
        }

    errors = []

    # Step 1: Check Python syntax
    try:
        ast.parse(code)
    except SyntaxError as e:
        errors.append(
            {
                "line": e.lineno or 0,
                "column": e.offset or 0,
                "code": "E999",
                "message": f"SyntaxError: {e.msg}",
            }
        )
        return {
            "valid": False,
            "errors": errors,
            "message": "Syntax errors found",
        }

    # Step 2: Run Ruff for critical errors only
    # E9: Syntax errors, F63: Invalid print, F7: Syntax errors, F82: Undefined names
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            temp_file = f.name

        try:
            process = await asyncio.create_subprocess_exec(
                "ruff",
                "check",
                "--select=E9,F63,F7,F82",
                "--output-format=json",
                temp_file,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            if stdout:
                ruff_results = json.loads(stdout.decode())
                for result in ruff_results:
                    errors.append(
                        {
                            "line": result.get("location", {}).get("row", 0),
                            "column": result.get("location", {}).get("column", 0),
                            "code": result.get("code", ""),
                            "message": result.get("message", ""),
                        }
                    )
        finally:
            Path(temp_file).unlink(missing_ok=True)

    except Exception:
        # If Ruff fails, just return syntax check result
        pass

    if errors:
        return {
            "valid": False,
            "errors": errors,
            "message": f"Found {len(errors)} error(s)",
        }

    return {
        "valid": True,
        "errors": [],
        "message": "Code is valid",
    }
