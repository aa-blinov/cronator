# Architecture

How Cronator is put together.

Everything runs in one FastAPI process: the web interface, the REST API and
the scheduler. There is no message queue, no separate worker and no
distributed state. The scripts themselves are the exception, and each one
runs as its own OS process in its own virtual environment.

## The shape

| Path | What it is responsible for |
| --- | --- |
| `app/main.py` | The application, the lifespan, the logging setup, `/health` and `/metrics`. |
| `app/api/` | The routers: scripts, executions, settings, users, diagnostics, rate limiting, locale and the HTML pages. |
| `app/services/executor.py` | The execution engine. Every run goes through it. |
| `app/services/scheduler.py` | The APScheduler wrapper, one job per enabled script, plus the daily cleanup job. |
| `app/services/environment.py` | The `uv` virtual environments: creation, dependency resolution, installation and the install stream. |
| `app/services/alerting.py` | The failure and success alerts, over SMTP or a webhook. |
| `app/services/backup_service.py` | The in-app backup, in the format the restore endpoint reads. |
| `app/services/cleanup_service.py` | The pruning of the execution history and of the old artifacts. |
| `app/services/settings_service.py` | The settings table, the fallback to the environment, and the encryption of the sensitive keys. |
| `app/services/metrics.py` | The Prometheus counters. |
| `app/models/` | The SQLAlchemy models, one module per table. |
| `app/schemas/` | The Pydantic request and response models. |
| `app/templates/` | The Jinja2 pages. |
| `app/static/` | The Tailwind input, the compiled bundle, the front-end script, the favicon and the fonts. |
| `app/middleware/` | The security headers and the CSRF origin guard. |
| `app/script_templates.py` | The 19 built-in script templates, as source strings. |
| `cronator_lib/` | The library every script imports: logging, artifacts, notifications, timing, context. |
| `alembic/versions/` | The migrations, one linear chain. |

## The data flow

The path of a request:

```
browser or curl
  -> SecurityHeadersMiddleware, CsrfOriginGuardMiddleware
  -> verify_credentials  (HTTP Basic, the users table, the environment as a fallback)
  -> app/api/scripts.py, app/api/executions.py   (JSON)
     app/api/pages.py                            (Jinja2 HTML)
  -> scheduler_service   (APScheduler, UTC)
  -> executor_service
  -> one OS process per run, in the script's own uv virtualenv
```

Every router except `/api/locale` requires `verify_credentials`, and the
check is at the router-include level in `app/api/__init__.py` rather than
on each endpoint. The locale router is open because the login page needs
the language switcher.

The path of a run:

```
execute_script
  -> a row in executions with the status running
  -> the work in a background task, not on the request
  -> a child process, with a minimal environment of its own
  -> stdout and stderr, line by line
  -> the database, and the in-memory replay buffer that feeds the SSE stream
  -> the row is finished, the counters on the script move, an alert may go out
```

## The execution engine

`app/services/executor.py` is the part worth understanding before touching
anything that runs a script.

`execute_script` is the single entry point. The scheduler calls it, the
Run button calls it, Test calls it, and a retry calls it. It checks the
free space on the artifact volume first and refuses the run with a failed
execution when there is not enough of it. It then takes a per-script
`asyncio.Lock`, so that the check for a script that is already running is
atomic: with `prevent_overlap` on, the second run is stored as a skipped
execution; with it off, the second run raises.

The row in the `executions` table is created with the status running and
its id is returned to the caller at once. The work itself happens in a
background task, `_run_script`, so that the request does not wait for a
script that runs for an hour.

`_run_script` resolves the virtual environment, builds a minimal
environment for the child process, and starts it with
`asyncio.create_subprocess_exec`. stdout and stderr are read line by line,
and every line goes into the database and into an in-memory replay buffer.
The timeout is enforced around the read, so a script that hangs without
printing anything is still stopped.

Each run is a real, separate OS process. Two scripts run fully in parallel
and there is no global cap on how many may run at once.

When the run ends, the row is finished, `last_success_at`,
`last_failure_at` and `consecutive_failures` move on the script, an alert
goes out if the script asked for one, a retry is scheduled if the failure
counts allow it, and the metric counter moves.

## The scheduler

`app/services/scheduler.py` is a thin wrapper around APScheduler's
`AsyncIOScheduler`. One job per enabled script, with the id
`script_<id>`, parsed from the script's five-field cron expression and
evaluated in UTC.

`update_job()` always removes the job and adds it again. Every path that
touches a schedule has to reach it: the edit endpoint, the toggle, the
bulk actions, and the revert to an earlier version. A path that misses it
leaves the database showing the new cron expression while the live job
keeps firing on the old one.

A built-in job runs the daily cleanup of the execution history at 03:00
UTC. The database backup is not in the application: it is a shell loop in
the `db-backup` service of `docker-compose.yml`.

## The virtual environments

`app/services/environment.py` owns one directory per script under
`envs/<script_name>/`. The environment is created with
`uv venv --python <version>`, the requested packages are resolved with
`uv pip compile` before anything is written to disk, `cronator_lib` is
installed in editable mode, and the script's own dependencies go in last.
The installation streams its own log lines to the browser over SSE, so a
slow install does not hold the request open.

This gives dependency isolation between scripts. It does not give resource
isolation: there is no CPU or memory limit, and no filesystem or network
sandbox. Every script runs as the same OS user as the application, with
the same view of the filesystem.

## The data model

| Table | What it holds |
| --- | --- |
| `scripts` | One row per script: the content, the cron expression, the reliability settings, the alert flags and the rolling counters. |
| `executions` | One row per run: the status, stdout, stderr, the exit code, the duration, the trigger and the number of the attempt. |
| `artifacts` | The files a script saved with `cronator_lib.save_artifact()`, one row per file. |
| `script_versions` | Content snapshots, deduplicated by the SHA-256 of the content. A save that changes nothing creates no version. |
| `script_audit_log` | The field-level history of the edits: the old value, the new value and who changed it. |
| `settings` | The settings that can be changed at runtime: SMTP, the webhook URL, the theme and the locale. |
| `users` | The accounts, with the roles the API checks. |
| `user_audit_log` | The history of the changes made to the accounts. |

Every datetime column is timezone-aware and the code works in UTC
throughout. A stateless test asserts that every `DateTime` column in the
model metadata declares `timezone=True`, so a column that drifts from the
PostgreSQL `TIMESTAMPTZ` cannot be added without the test failing.

## The background jobs

| Job | When | Where |
| --- | --- | --- |
| A script run | On the cron schedule, on demand, or on a retry | `scheduler_service` into `executor_service` |
| The cleanup of the execution history | Every day at 03:00 UTC | `scheduler_service._run_cleanup` into `cleanup_service` |
| The cleanup of the stale executions | Once, at the start of the process | `executor_service.cleanup_stale_executions()` in the lifespan |
| The database backup | Every day at 02:00, on the clock of the host | The `db-backup` service in `docker-compose.yml` |

The cleanup of the stale executions runs only at the start, and not on a
schedule. An execution that gets stuck at running because of a failure in
the middle of a run stays stuck until the next restart.

## Decisions worth knowing about

### The run does not wait for the request

The request creates the row and returns the id. The script runs in a
background task. The caller watches the run over SSE, and the interface
polls the same endpoint when the stream is not available.

The cost is that a run can go on after the browser is closed, and the
cost is paid on purpose: a script that takes an hour must not hold a
request open for an hour.

### The child process gets a minimal environment of its own

Only `PATH`, `HOME`, `LANG`, `TZ`, the Oracle client variables, the
`CRONATOR_*` context variables and the script's own `environment_vars` are
passed on. Nothing from the environment of the application reaches a
script, so a credential that the application holds cannot leak into a
script that prints its own environment.

### The failure path rolls the session back first

A commit that fails leaves the session dirty, and the next query raises
the same error again. That skips `close_stream()` and leaves the
execution stuck at running until the next restart. The rollback sits
before the row is marked failed, and it stays there.

### The stream state is dropped after a grace period

While a run is going, the events are broadcast from an in-memory
`ExecutionStreamState` keyed by the id of the execution, so a browser
that reconnects can resume from the `Last-Event-ID` it was given. When
the stream is closed, the state is dropped after five minutes. A client
that reconnects after that falls back to the stdout and stderr that were
stored in the database.

### The scripts are not sandboxed

Each script gets its own virtual environment, so two scripts can pin
different versions of the same package, and nothing more is promised by
it. The scripts run as the same user as the application, with the same
filesystem and the same network, and there is no limit on their memory or
their CPU time.

## Boundaries

- **`app/api/` may not run a script.** The routers call the executor
  service, and the executor service is the only thing that starts a
  process.
- **`app/services/executor.py` may not know about the request.** It takes
  a script and returns an execution id.
- **`app/services/environment.py` owns the virtual environments.**
  Nothing else creates one or installs into one.
- **`app/models/` holds the tables and nothing else.** The services use
  them, and the routers answer with them.
- **`cronator_lib/` is the only thing a script imports.** It is installed
  into the environment of every script, and it knows nothing about the
  application.
- **Every endpoint that changes state takes `require_admin`.**
- **The clock is UTC.** Every timestamp is timezone-aware, and a column
  without `timezone=True` fails the stateless test.
