"""Page routes for HTML templates."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app import __version__
from app.api.dependencies import verify_credentials
from app.config import get_settings
from app.database import get_db
from app.models.execution import Execution, ExecutionStatus
from app.models.script import Script
from app.models.script_version import ScriptVersion
from app.script_templates import get_templates
from app.services.executor import executor_service
from app.services.scheduler import scheduler_service

router = APIRouter()
DEFAULT_THEME = "dim"

async def _get_user_theme() -> str:
    """Return the persisted theme preference (default: 'dim')."""
    from app.services.settings_service import settings_service

    try:
        return await settings_service.get("theme", "dim")
    except Exception:
        return "dim"


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
            "version": __version__,
            "theme": DEFAULT_THEME,
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


@router.get("/scripts", response_class=HTMLResponse)
async def scripts_list(
    request: Request,
    page: int = 1,
    per_page: int = 50,
    search: str | None = None,
    status: str | None = Query(None),
    username: str = Depends(verify_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Q1: dedicated /scripts page — sortable list with search, status filter,
    pagination, and a bulk-action toolbar (enable / disable / delete)."""
    like = f"%{search.strip()}%" if search and search.strip() else None
    base_query = select(Script)
    if like:
        base_query = base_query.where(
            or_(
                Script.name.ilike(like),
                Script.description.ilike(like),
                Script.cron_expression.ilike(like),
                Script.content.ilike(like),
            )
        )
    if status == "enabled":
        base_query = base_query.where(Script.enabled.is_(True))
    elif status == "disabled":
        base_query = base_query.where(Script.enabled.is_(False))

    count_query = select(func.count()).select_from(base_query.subquery())
    total = await db.scalar(count_query) or 0

    query = base_query.order_by(Script.name)
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    scripts = result.scalars().all()

    return request.app.state.templates.TemplateResponse(
        "scripts.html",
        {
            "request": request,
            "page_title": "Scripts",
            "theme": DEFAULT_THEME,
            "scripts": scripts,
            "filters": {
                "search": search if search and search.strip() else None,
                "status": status if status and status.strip() else None,
            },
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "pages": (total + per_page - 1) // per_page,
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
            "version": __version__,
            "theme": DEFAULT_THEME,
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
            "script_templates": get_templates(),
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
            "version": __version__,
            "theme": DEFAULT_THEME,
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
            "version": __version__,
            "theme": DEFAULT_THEME,
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
            "app_version": __version__,
        },
    )


@router.get("/executions", response_class=HTMLResponse)
async def executions_list(
    request: Request,
    page: int = 1,
    script_id: str | None = Query(None),
    status: str | None = Query(None),
    search: str | None = Query(None),
    username: str = Depends(verify_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Executions list page."""
    per_page = 50

    # Parse script_id if provided
    parsed_script_id = None
    if script_id and script_id.strip():
        try:
            parsed_script_id = int(script_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="script_id must be a valid integer")

    query = select(Execution).options(joinedload(Execution.script))

    if parsed_script_id:
        query = query.where(Execution.script_id == parsed_script_id)
    if status and status.strip():
        query = query.where(Execution.status == status)
    # Q2: server-side search across stdout/stderr/script name
    if search and search.strip():
        like = f"%{search.strip()}%"
        query = query.join(Script, Execution.script_id == Script.id).where(
            or_(
                Execution.stdout.ilike(like),
                Execution.stderr.ilike(like),
                Script.name.ilike(like),
            )
        )

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
            "version": __version__,
            "theme": DEFAULT_THEME,
            "executions": executions,
            "scripts": scripts,
            "filters": {
                "script_id": parsed_script_id,
                "status": status if status and status.strip() else None,
                "search": search if search and search.strip() else None,
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
            "version": __version__,
            "theme": DEFAULT_THEME,
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
            "version": __version__,
            "theme": DEFAULT_THEME,
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


@router.post("/executions/{execution_id}/rerun")
async def rerun_execution_action(
    execution_id: int,
    username: str = Depends(verify_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Re-run the script that produced this execution."""
    result = await db.execute(
        select(Execution).where(Execution.id == execution_id)
    )
    execution = result.scalar_one_or_none()
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    new_execution_id = await executor_service.execute_script(
        execution.script_id, triggered_by="manual"
    )
    return RedirectResponse(
        url=f"/executions/{new_execution_id}",
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


@router.get("/changelog", response_class=HTMLResponse)
async def changelog_page(
    request: Request,
    username: str = Depends(verify_credentials),
):
    """Render the project CHANGELOG.md as a simple styled HTML page.

    We don't pull in a full markdown library to avoid the dependency; instead
    we use Python-Markdown if available, otherwise a tiny built-in renderer
    that handles headings, lists, bold, links, and fenced code blocks.
    """
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[2]
    changelog_path = project_root / "CHANGELOG.md"

    if not changelog_path.exists():
        return HTMLResponse(
            "<h1>Changelog unavailable</h1><p>CHANGELOG.md not found.</p>",
            status_code=404,
        )

    raw = changelog_path.read_text(encoding="utf-8")

    try:
        import markdown as _md  # type: ignore

        body_html = _md.markdown(
            raw,
            extensions=["fenced_code", "tables", "toc"],
        )
    except ImportError:
        body_html = _minimal_markdown(raw)

    return HTMLResponse(
        f"""<!doctype html>
<html lang="en" data-theme="dim">
<head>
  <meta charset="utf-8">
  <title>Changelog - Cronator</title>
  <link rel="icon" type="image/svg+xml" href="/static/favicon.svg">
  <link rel="stylesheet" href="/static/output.css">
  <style>
    body{{max-width:880px;margin:0 auto;padding:32px 24px;font-family:ui-sans-serif,system-ui,sans-serif;}}
    h1,h2,h3{{color:#38bdf8;border-bottom:1px solid #1e293b;padding-bottom:8px;}}
    h2{{margin-top:40px;}}
    h3{{margin-top:24px;color:#94a3b8;}}
    pre{{background:#020617;padding:14px 16px;border-radius:8px;overflow:auto;color:#e2e8f0;}}
    code{{background:#1e293b;padding:2px 6px;border-radius:4px;font-size:0.9em;}}
    a{{color:#60a5fa;}}
    ul li{{margin:4px 0;}}
    .badge{{display:inline-block;background:#0ea5e9;color:white;padding:2px 8px;border-radius:6px;font-size:12px;margin-left:8px;}}
  </style>
</head>
<body>
  <p><a href="/">&larr; Back to dashboard</a></p>
  <h1>Cronator Changelog</h1>
  {body_html}
</body>
</html>
"""  # noqa: E501
    )


def _minimal_markdown(text: str) -> str:
    """Tiny fallback renderer used when the `markdown` package is not installed.

    Handles the subset we actually use in CHANGELOG.md: #/##/### headings,
    - bullets, fenced code blocks, and links.
    """

    lines = text.split("\n")
    out: list[str] = []
    in_code = False
    in_ul = False
    for line in lines:
        if line.startswith("```"):
            if in_code:
                out.append("</pre>")
                in_code = False
            else:
                out.append("<pre>")
                in_code = True
            continue
        if in_code:
            out.append(line)
            continue
        if line.startswith("### "):
            if in_ul:
                out.append("</ul>")
                in_ul = False
            out.append(f"<h3>{_inline(line[4:])}</h3>")
        elif line.startswith("## "):
            if in_ul:
                out.append("</ul>")
                in_ul = False
            out.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("# "):
            if in_ul:
                out.append("</ul>")
                in_ul = False
            out.append(f"<h1>{_inline(line[2:])}</h1>")
        elif line.startswith("- "):
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{_inline(line[2:])}</li>")
        elif line.strip() == "":
            if in_ul:
                out.append("</ul>")
                in_ul = False
            out.append("")
        else:
            if in_ul:
                out.append("</ul>")
                in_ul = False
            out.append(f"<p>{_inline(line)}</p>")
    if in_ul:
        out.append("</ul>")
    if in_code:
        out.append("</pre>")
    return "\n".join(out)


def _inline(text: str) -> str:
    import re

    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text
