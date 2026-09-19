# Architecture

## Stack

- **FastAPI** (async) serves both the REST API and the server-rendered HTML
  pages (Jinja2 + Tailwind/DaisyUI, no separate frontend build for the app
  shell — only the CSS is compiled at Docker build time).
- **SQLAlchemy 2.0 (async)** — SQLite (`aiosqlite`) for local development,
  PostgreSQL (`asyncpg`) in Docker/production.
- **Alembic** for schema migrations, run automatically on container start.
- **APScheduler** (`AsyncIOScheduler`) drives cron-triggered executions and
  the daily internal cleanup job, in-process — no separate worker/broker.
- **uv** manages a dedicated virtualenv per script (own Python version,
  own dependencies), so one script's `requests==2.28` doesn't collide with
  another's `requests==2.31`.

There is no message queue, no separate worker process, and no distributed
state — everything runs in a single FastAPI process. That's a deliberate
scope choice (see the README's framing: a gap-filler between bare `cron` and
a full orchestrator), not an oversight; scaling out would need a different
architecture (see [Deployment → Scaling limits](DEPLOYMENT.md#scaling-limits)).

## Request flow

```
Browser / curl
      │
      ▼
SecurityHeadersMiddleware  (CSP, HSTS, etc. — app/middleware/security_headers.py)
      │
      ▼
verify_credentials  (Basic Auth against the User table, env fallback)
      │
      ▼
┌─────────────────┬──────────────────┬────────────────────┐
│  /api/scripts    │  /api/executions │  / , /scripts, ... │
│  (app/api/       │  (app/api/       │  (app/api/pages.py │
│   scripts.py)    │   executions.py) │   — HTML views)    │
└─────────────────┴──────────────────┴────────────────────┘
      │                     │
      ▼                     ▼
  scheduler_service    executor_service
  (app/services/       (app/services/
   scheduler.py)        executor.py)
```

All API routers except `/api/locale` (needed by the unauthenticated login
page for the language switcher) require `verify_credentials` at the
router-include level (`app/api/__init__.py`), not per-endpoint.

## The execution engine (`app/services/executor.py`)

This is the part worth understanding before touching anything else.

1. **`execute_script(script_id, ...)`** is the single entry point, called by
   the scheduler, the "Run" button, "Test", "Re-run", and retries alike.
   - Checks free disk space first (`min_free_space_mb`) and refuses with a
     visible `FAILED` execution if it's too low — see
     [Operations → Disk space](OPERATIONS.md#disk-space).
   - Acquires a per-script `asyncio.Lock` to make the "is this script
     already running" check atomic, then either starts a new run, creates a
     `SKIPPED` execution (if `prevent_overlap=True` and one is already
     running), or raises (`prevent_overlap=False`).
   - Creates the `Execution` row (`status=RUNNING`) and returns its ID
     immediately — the actual run happens in a fire-and-forget
     `asyncio.Task` (`_run_script`), not on the request's coroutine.
2. **`_run_script`** does the real work: resolves the script's venv
   (`environment_service`), builds a minimal `env` dict for the child
   process (nothing from Cronator's own environment leaks in — see
   [Security](SECURITY.md)), spawns it with
   `asyncio.create_subprocess_exec`, streams stdout/stderr line-by-line into
   both the DB (final) and an in-memory replay buffer (for live SSE), and
   enforces `script.timeout` via `asyncio.wait_for`.
   - Each execution is a **real, separate OS process** — not a thread, not
     an in-process function call. Different scripts run fully in parallel;
     there's no global concurrency cap (see
     [Security → Script execution model](SECURITY.md#script-execution-model)
     for what that does and doesn't protect against).
   - On completion, `_finish_execution` updates the row, updates
     `Script.last_success_at` / `last_failure_at` / `consecutive_failures`,
     fires alerts (`_send_failure_alert` / `_send_success_alert`), and
     schedules a retry if `retry_count` / `retry_delay` /
     `max_retry_window` say to.
   - The outer `except` block (if something raises *before* reaching the
     normal finish path) rolls back the DB session before retrying to mark
     the execution `FAILED` — a session left dirty by a failed commit would
     otherwise raise again on the very first query, skip `close_stream()`,
     and leave the execution stuck at `RUNNING` forever.
3. **Live streaming** (`GET /api/executions/{id}/stream`, SSE): while an
   execution is running, events are broadcast from an in-memory
   `ExecutionStreamState` (per execution ID) so reconnecting clients can
   resume from a `Last-Event-ID`. Once a stream is closed, replay state is
   dropped after a grace period; reconnecting after that falls back to the
   execution's stored `stdout`/`stderr` from the DB.

## Scheduler (`app/services/scheduler.py`)

A thin wrapper around APScheduler's `AsyncIOScheduler`:

- One APScheduler job per enabled script (`job_id = f"script_{script.id}"`),
  parsed from the script's 5-field cron expression.
- `update_job()` always does remove-then-add — every code path that changes
  a script's schedule or enabled state (`PUT /scripts/{id}`, toggle, bulk
  actions, **and reverting to a previous version**) must call it, or the
  live job silently keeps running on the old schedule while the DB shows
  the new one.
- A built-in internal job (`_register_internal_jobs`) runs the daily
  execution-history cleanup at 03:00 UTC — this is separate from the
  Postgres backup service, which is a shell loop in `docker-compose.yml`,
  not part of the app process.

## Environment isolation (`app/services/environment.py`)

Each script gets its own directory under `envs/<script_name>/` containing a
`uv`-managed virtualenv. Dependencies are validated (`uv pip compile`-style
resolution check) before being written to disk. Installation streams its
own logs over SSE (`POST /api/scripts/{id}/install` +
`GET .../install-stream`) so a slow `pip install` doesn't block the request.

This gives dependency isolation between scripts. It does **not** give
resource isolation (CPU/memory limits) or filesystem/network sandboxing —
every script's subprocess runs as the same OS user (`cronator`) with the
same filesystem visibility as the app itself. See
[Security](SECURITY.md#script-execution-model).

## Data model

| Table               | Purpose                                                                                     |
| ------------------- | --------------------------------------------------------------------------------------------- |
| `scripts`           | One row per scheduled script: content, cron expression, reliability settings, alert flags, and rolling stats (`last_success_at`, `consecutive_failures`, `last_alert_at` / `last_failure_alert_at`) |
| `executions`        | One row per run: status, stdout/stderr, exit code, duration, `triggered_by`, retry `attempt`   |
| `artifacts`         | Files a script saved via `cronator_lib.save_artifact()`, one row per file, cascades on execution delete |
| `script_versions`   | Content snapshots, deduplicated by SHA-256 hash — a save that doesn't actually change content/deps/python_version doesn't create a new version |
| `script_audit_log`  | Field-level change history for script edits (old value → new value, who changed it)            |
| `settings`          | Runtime-configurable settings (SMTP, webhook URL, theme, locale) — see [Configuration](CONFIGURATION.md) for env vs. DB precedence |
| `users`             | Multi-user accounts for F21 RBAC — see [Security](SECURITY.md#rbac) for its actual scope       |

All datetime columns are `TIMESTAMPTZ` (timezone-aware) — the app works in
UTC throughout (`datetime.now(UTC)`), and a stateless test
(`tests/stateless/test_model_timezone_consistency.py`) asserts every
`DateTime` column declares `timezone=True` so a future model can't drift
from that without a schema diff.

## Background jobs summary

| Job                              | Trigger                          | Where                                    |
| --------------------------------- | --------------------------------- | ------------------------------------------ |
| Script execution                 | Cron schedule / manual / retry    | `scheduler_service` → `executor_service`  |
| Execution history cleanup        | Daily, 03:00 UTC                  | `scheduler_service._run_cleanup` → `cleanup_service.cleanup_by_status()` |
| Stale execution cleanup          | Once, at app startup only         | `executor_service.cleanup_stale_executions()` in `app/main.py`'s lifespan |
| Database backup                  | Daily, ~02:00 (host clock)        | `db-backup` service in `docker-compose.yml` — a shell loop, not app code |

The stale-execution cleanup running only at startup (not periodically)
matters operationally: an execution that gets stuck at `RUNNING` due to an
unhandled failure mid-run won't self-heal until the next restart. See
[Operations → Troubleshooting](OPERATIONS.md#troubleshooting).
