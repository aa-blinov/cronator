# AGENTS.md — agent context for `cronator`

Cronator is a self-hosted scheduler for Python scripts: FastAPI serves a web
interface and a REST API, APScheduler fires the cron jobs, and every script
runs as its own OS process in its own `uv` virtualenv. The whole thing runs
in one process, with PostgreSQL in the Docker stack and SQLite for local
development.

This file is what you need to work on the project without reading all of it.

## Run / build / test

```bash
uv sync --all-extras                                   # install
uv run alembic upgrade head                             # migrate
uv run python -m uvicorn app.main:app --reload --port 8080   # run the app
uv run pytest tests/stateless tests/stateful -v         # fast path, SQLite
npm run test:docker                                     # what CI runs, PostgreSQL 16
uv run pytest tests/pg/ -v                             # the PostgreSQL subset
uv run pytest tests/ui/ -v                             # Playwright, against a running stack
uv run ruff check .                                    # lint
npm run build:css                                      # rebuild the Tailwind bundle
```

`npm run test:docker` is `docker compose -f docker-compose.test.yml up
--build --abort-on-container-exit --exit-code-from tests`. It builds the
`tests` service from the Dockerfile's `builder` target against a
`postgres:16-alpine` container, with `SKIP_ALEMBIC_MIGRATIONS=1` and the
schema built from the SQLAlchemy models.

The Playwright tests need `playwright==1.49.0` and a Chromium download, and
they run against the live stack at `http://localhost:8080`, so they never
run inside the Docker test container.

## Where things live

| Path | What it holds |
| --- | --- |
| `app/main.py` | The app, the lifespan, the logging setup, the exception handlers, `/health` and `/metrics`. |
| `app/api/` | One router per resource. `scripts.py` is the largest; `pages.py` renders the HTML. |
| `app/services/executor.py` | The execution engine. Read this before touching anything that runs a script. |
| `app/services/scheduler.py` | The APScheduler wrapper, plus the two internal jobs (cleanup at 03:00, backup at 02:00). |
| `app/services/environment.py` | The `uv` virtualenvs: creation, dependency resolution, installation, streaming. |
| `app/services/settings_service.py` | The settings table, the environment fallback, and the Fernet encryption of the sensitive keys. |
| `app/services/backup_service.py` | The in-app backup, in the COPY-block format the restore endpoint understands. |
| `app/models/`, `app/schemas/` | SQLAlchemy models and Pydantic schemas, one module per table. |
| `app/templates/`, `app/static/` | The Jinja2 pages and the Tailwind bundle. |
| `app/script_templates.py` | The 19 built-in templates, as source strings. |
| `cronator_lib/` | The library every script imports: logging, artifacts, notifications, timing, context. |
| `alembic/versions/` | The migrations, one linear chain. Check `alembic heads` before adding one. |
| `tests/stateless/` | Pure unit tests, no database, no client. |
| `tests/stateful/` | The fixtures and the full API surface. |
| `tests/pg/` | A subset re-run against a real PostgreSQL, to catch SQLite-only assumptions. |
| `tests/ui/` | Playwright flows and their baseline screenshots. |

## Traps

- **The test image caches the source.** After editing anything under `app/`,
  `tests/` or the `Dockerfile`, run
  `docker compose -f docker-compose.test.yml build tests` before running the
  suite. Without it the container runs the old code and the tests pass
  against the wrong version.
- **`update_job()` must be called on every path that touches the schedule.**
  Enable, disable, edit, bulk action and revert all have to reach
  `scheduler_service.update_job()`. Miss one and the database shows the new
  cron expression while the live job keeps firing on the old one.
- **`ADMIN_PASSWORD` and `SECRET_KEY` have no defaults.** The settings model
  requires them, and it raises at startup if either still holds the
  `.env.example` placeholder. `SUPPRESS_CONFIG_WARNINGS=1` silences the
  length warnings, not that check. The CI jobs set both variables in the
  workflow environment for the same reason.
- **Never use a flat `asyncio.sleep()` after triggering a run.** A test that
  starts a script and then asserts on it is flaky on a slow runner. Poll
  `last_run_status` on `/api/scripts/{id}` with an explicit set of terminal
  statuses (`succeeded`, `failed`, `cancelled`, `timeout`, `skipped`); `None`
  compares equal to `None`, so a "any non-running" check returns at once.
- **Every `DateTime` column declares `timezone=True`.** A bare `DateTime()`
  drifts from the PostgreSQL `TIMESTAMPTZ` column and `alembic check` then
  reports a phantom migration. A stateless test enforces this across the
  whole model metadata.
- **`tests/pg/` is a sibling of `tests/stateful/`, not a descendant.** Pytest
  only walks up a test file's own directory, so `tests/pg/conftest.py` has
  to re-export the fixtures it needs from `tests/stateful/conftest.py`. A
  new DB fixture has to be added to that re-export list as well, or the
  PostgreSQL job fails with "fixture not found".
- **The failure alert throttle uses its own column.** `last_failure_alert_at`
  is separate from `last_alert_at` on purpose: a success alert writes
  `last_alert_at`, and sharing the column let a success reset the failure
  window and silence the alert for a script that is genuinely broken.
- **The child process gets a minimal, explicit environment.** Only `PATH`,
  `HOME`, `LANG`, `TZ`, the Oracle client variables, the `CRONATOR_*`
  context variables and the script's own `environment_vars` are passed. No
  ambient credential of Cronator's own reaches a script.
- **Two different registries hold the running processes.**
  `executor_service.running_processes` holds the script's own process;
  `environment_service._active_processes` holds the `uv` subprocess. The
  graceful shutdown kills both, and the executor's dictionary never contains
  an environment setup.
- **The failure path rolls the session back first.** A failed commit leaves
  the session dirty, and the next query raises the same error again, which
  skips `close_stream()` and leaves the execution stuck at `running` until
  the next restart. Keep the rollback where it is.
- **Ruff ignores `tests/**` for the line length only.** `F401`, `F841` and
  `F541` still fire on test files, and the CI lint job blocks the merge on
  them.
- **The compose validation job stubs `.env` from `.env.example`.**
  `docker compose config` exits 1 when `env_file: .env` points at a missing
  file, so that step in `.github/workflows/ci.yml` has to stay.
- **The hadolint action is pinned to a commit SHA.** The `hadolint/hadolint-action`
  tags are not guaranteed to exist, and a floating tag fails the build for a
  reason that has nothing to do with the code.

## Style / safety rails

- **Comments explain why, never what.** The codebase holds to this, and the
  comments are usually about a failure mode that has already happened. Keep
  it that way.
- **Every new mutating endpoint takes `require_admin`,** including the HTML
  action routes in `app/api/pages.py`. The whole router is authenticated at
  the include in `app/api/__init__.py`; do not add an endpoint that escapes
  it, and do not add a second router without the dependency.
- **A new secret goes into `SENSITIVE_KEYS`** in
  `app/services/settings_service.py`, or it sits in the database in
  plaintext.
- **The interface must not promise isolation the code does not provide.**
  Scripts share the `cronator` OS user and the filesystem; there is no CPU
  or memory limit per script. `docs/SECURITY.md` says so explicitly, and
  any new copy has to agree with it.
- **The name of a script becomes a directory name.** The schema allows
  letters, digits, `_` and `-` only, and the name cannot start or end with
  `-` or `_`.
- **A run is a row in `executions`.** Any new outcome gets a status, a
  `finished_at` and a duration, or the history and the metrics drift apart.

## Where the product truth lives

`PRODUCT.md` holds it. Read it before changing what the product does, and
write the change there when the behaviour changes.
