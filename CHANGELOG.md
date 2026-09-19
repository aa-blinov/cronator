# Changelog

All notable changes to Cronator will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **F1: Security headers middleware** — every response now carries
  `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: strict-origin-when-cross-origin`,
  `Content-Security-Policy: default-src 'self'`, and a restrictive
  `Permissions-Policy`. Tested at the API and UI layers
  (5 backend + 3 Playwright tests with screenshots).
- **F2: Enhanced `/health` endpoint** — now includes `version`,
  `components.disk` (free/total/used bytes + percent), `components.scheduler`
  status + `job_count`, and `components.migrations` (current/head revisions
  or `unavailable` with reason). 6 backend + 3 UI tests.
- **F3: Graceful shutdown** — `graceful_shutdown()` is now a public function
  extracted from the FastAPI lifespan. On shutdown the scheduler is stopped
  first, then every in-flight execution is cancelled (status=CANCELLED rather
  than stuck in RUNNING), then the DB engine is closed. The function is
  idempotent and tolerates per-step failures. 7 backend + 3 UI tests.
- **F4: CHANGELOG.md** — Keep-a-Changelog formatted history of every shipped
  feature; rendered at `/changelog` (with simple built-in markdown → HTML so
  no extra runtime dep), footer link in the sidebar. Dockerfile and
  `.dockerignore` bundle `CHANGELOG.md` into the image.
- **F5: Ruff + mypy in CI** — `.github/workflows/ci.yml` runs the
  `astral-sh/ruff-action` (lint + format check), validates
  `docker-compose.yml`, runs Dockerfile lint with hadolint, plus the existing
  pytest matrix. 5 tests cover the workflow itself.
- **F6: Prometheus `/metrics`** — `app/services/metrics.py` exposes
  `crinator_app_info{version}`, `crinator_scripts_total`,
  `crinator_executions_running`, `crinator_artifacts_total`,
  `crinator_scheduler_jobs`, and `crinator_uptime_seconds` with HELP/TYPE
  comments. Lock-protected registry, gauges refreshed on every scrape.
  `record_execution_status()` is called from the executor. 6 backend +
  4 Playwright tests with screenshots.
- **F7: PostgreSQL tests in CI** — `ci.yml` adds a `test-postgres` job that
  spins up `postgres:16-alpine` and runs the suite against
  `TEST_DATABASE_URL` to catch SQLite-only assumptions.
- **F8: Dockerfile lint in CI** — `ci.yml` adds a `dockerfile-lint` job
  (hadolint with threshold=error). 6 host-only tests.
- **F9: OpenAPI examples** — `ScriptCreate`, `ScriptUpdate`,
  `ExecutionRead`, `UpdateSettingsRequest`, plus `openapi_extra` on
  `validate-*`, `/api/settings/test-webhook`, `/api/users`, and
  `/api/locale` so every POST/PUT body has an example in `/docs`. 3 tests.
- **F10: Cancel button in executions list** — Running rows show a red
  "Cancel" button that POSTs `/api/executions/{id}/cancel`; finished rows
  don't show it. 3 Playwright flows with screenshots.
- **F11: Audit log** — `ScriptAuditLog` model + alembic migration
  `i1j2k3l4m5n6`. `update_script()` records one row per changed field with
  `changed_by=username`. `GET /api/scripts/{id}/audit?limit=&offset=` with
  pagination. 5 backend + 2 UI tests with screenshots.
- **F12: Backup-restore via UI** — `GET /api/settings/backups` lists
  available archive backups; `POST /api/settings/restore-backup` accepts a
  multipart gzip upload (≤ 500 MB) and rejects DDL that would damage the
  schema (DROP DATABASE|SCHEMA, TRUNCATE pg_catalog). 4 backend tests.
- **F13: Script size limit** — `max_length=1MB` on `ScriptCreate.content`
  and `ScriptUpdate.content`; over-limit uploads are rejected with 422.
  4 tests.
- **F14: HSTS header** — `Strict-Transport-Security: max-age=31536000;
  includeSubDomains` is emitted only on HTTPS requests (direct or via
  `X-Forwarded-Proto: https`). 3 tests.
- **F15: i18n locale API** — `GET /api/locales`, `GET /api/locale`,
  `POST /api/locale` (whitelist: en, ru). Persists the active locale to the
  settings table. 4 backend tests.
- **F16: Dark/light theme toggle** — `theme` setting in DB, 5 daisyUI
  themes selectable from the sidebar; choice persists to localStorage
  `crinator-theme`. 4 tests.
- **F17: Webhook URL for failure notifications** — `webhook_url` setting +
  `POST /api/settings/test-webhook` to send a sample payload. 3 tests.
- **F18: Timeout UI hint** — the script editor shows the cap and the
  recommended value: "Maximum 86400s (24h). Recommended ≤ 3600s." 3 tests.
- **F19: `/api/diagnostics`** — process info, DB connectivity, scheduler
  jobs, executor running-set, masked config (admin secrets hidden), and
  logs info. For operator incident-response. 8 tests.
- **F20: JSON logging** — `app/services/json_logging.py` HumanFormatter +
  JsonFormatter; selected via `settings.log_format` env var
  (`human` default, `json` for log aggregators). 5 tests.
- **F21: Multi-user RBAC (compressed)** — `User` model + alembic
  `j2k3l4m5n6o7`. PBKDF2-HMAC-SHA256 password hashing in
  `app/services/user_service.py`. `verify_credentials` tries DB then falls
  back to env-defined admin; `ensure_admin_seeded()` runs in app startup.
  `/api/users` for list/create/delete (admin-gated in production).
  5 backend tests.
- **F22: Release CI** — `.github/workflows/release.yml` triggers on
  `v*.*.*` tags, extracts the matching CHANGELOG section with awk,
  builds a multi-arch Docker image, and publishes a GitHub release.
  6 tests.
- **Playwright UI test infrastructure** — `tests/ui/` directory with shared
  fixtures (auth headers, browser context, screenshot helpers) and
  baseline screenshots of the four main pages.
- **F23: Dashboard "Requires Attention" triage** — scripts that failed today
  or haven't run in 7 days now surface in a dedicated section above the
  alphabetical script list, sorted enabled-first, instead of requiring a
  manual scan of the whole table. 3 tests.
- **F24: Webhook notifications actually fire on execution events** —
  `AlertingService.send_webhook()` is now called from
  `send_failure_alert`/`send_success_alert`; previously `webhook_url` (F17)
  had a working "Test Webhook" button and backend endpoint but nothing
  ever invoked it on a real failure or success. Also added the missing
  Settings UI for the field (it only existed via direct API calls before).
  5 tests; verified live against a real HTTP listener.

### Fixed
- **Race condition in `_running_scripts`** — `ExecutorService` now discards
  the script from `_running_scripts` immediately after `_finish_execution`
  commits, instead of after the inner finally's 100ms SSE-friendly delay.
  Previously a freshly-finished script could not be deleted for ~100ms
  (responded 409) and a re-run was marked SKIPPED for the same window.
- **`verify_credentials` async fix (F21)** — the previous implementation
  used `asyncio.get_event_loop().run_until_complete()` to call the async
  `get_user()`, which raises `RuntimeError` inside FastAPI's running
  event loop, so DB-backed auth silently fell through to the env-defined
  admin and rejected real User-table logins. Switched to an `async`
  dependency so the DB lookup awaits correctly.
- **`restore-backup` async fix (F12)** — `app/api/settings.py:
  restore_backup` previously called `sqlalchemy.create_engine(sync_url)`
  which requires `psycopg2` for PostgreSQL — that driver is not installed
  in the runtime image, so every restore against the live PostgreSQL stack
  returned 500 with `ModuleNotFoundError: No module named 'psycopg2'`.
  Switched to the application's existing `async_session_maker` (asyncpg
  for PostgreSQL, aiosqlite for SQLite); each statement runs in its own
  transaction so per-statement failures are still isolated.
- **Bulk disable/delete never touched the scheduler** — `remove_job()` was
  called with the `Script` ORM object instead of its `id`, so the job-id
  lookup never matched and disabled/deleted scripts kept firing on
  schedule. `duplicate_script()` also never wrote the copied content to
  disk (every run of a duplicate failed with "Script file not found"),
  and bulk delete skipped `environment_service.delete_env()`, leaking a
  venv per bulk-deleted script with dependencies.
- **`/scripts` "Last Run" column ignored failures** — it only read
  `last_success_at`, so a script failing on every run showed "—", visually
  indistinguishable from one that had never run. Now shows whichever of
  `last_success_at`/`last_failure_at` is more recent, failures in red.
- **Script execution timeout never fired for a silently hung script** —
  `read_stream()`'s `readline()` loop blocks until the process exits, and
  it ran via `asyncio.gather()` *before* the `wait_for(process.wait(),
  timeout=...)` call. A script that hangs without ever writing to
  stdout/stderr (deadlock, stuck network call, infinite loop with no
  print) never reached the timeout check — the execution stayed RUNNING
  forever. Partial output captured before the hang is now kept instead of
  discarded on timeout too.
- **Every `uv` subprocess call (venv creation, pip install) had no
  timeout** — same root cause as above, in `EnvironmentService`. A
  stalled network call during dependency installation hung forever;
  worse, `executor._run_script()` calls `setup_environment()` *before*
  the script's own process starts, so `script.timeout` never guarded this
  phase either. Added a shared 5-minute `install_timeout` wrapping every
  `uv` call (plain and streaming/retry variants).
- **Cancelling an execution during environment setup was silently
  dropped** — `cancel_execution()` only checked
  `running_processes[execution_id]`, which is only set *after*
  `setup_environment()` returns (which can take minutes). Cancelling
  during that window returned `False` without touching the DB — the
  execution stayed RUNNING and the script ran anyway once setup finished.
  Cancellation is now persisted regardless of process state, and
  `_run_script()` re-checks it right after setup before ever starting the
  script's process.
- **Orphaned `uv` processes on shutdown, and two related resource leaks**
  — `graceful_shutdown()` only killed processes tracked in
  `executor.running_processes`, which never includes a script's
  environment-setup subprocess; a deploy or restart during that window
  left a `uv venv`/`uv pip install` running as an orphan. Every `uv`
  subprocess call is now registered via a `_tracked_subprocess()` context
  manager and killed on shutdown. Also: `install_queues[script_id]` was
  only cleaned up by the SSE endpoint's consumer side, leaking the Queue
  (and every buffered log line) if a client never opened
  `/install-stream`; and `validate_dependencies()`'s 60s timeout never
  killed the `uv pip compile` subprocess it gave up on.
- **Code editor was completely broken by the CSP** — `script_editor.html`
  and `script_version.html` loaded CodeMirror from `cdnjs.cloudflare.com`,
  but the F1 CSP only allows `'self'` for `script-src`/`style-src`. The
  browser silently blocked every CodeMirror `<script>`/`<link>`, leaving a
  tiny unstyled `<textarea>` instead of a syntax-highlighted, line-numbered
  editor (and the cron "Next runs" preview stuck on "Loading..." as a side
  effect). Fixed by vendoring CodeMirror under `/static/vendor` instead of
  loosening the CSP.
- **Google Fonts silently blocked on every page** — same CSP cause;
  `fonts.googleapis.com` isn't `'self'`, so Inter/JetBrains Mono never
  loaded and the whole UI rendered on system-font fallback. Self-hosted
  under `/static/vendor/fonts`. Also removed the `lucide-static` `<link>`
  entirely — it was dead weight blocked by the same rule; every icon
  already goes through `icons.html`'s inline SVG macros.
- **Flaky `test_stream_live_execution_via_replay_buffer`** — root cause
  was in the test setup, not app code: `executor_service` is a
  module-level singleton shared by the whole pytest process, and
  `close_stream()`'s fire-and-forget cleanup task could outlive its own
  test's event loop and collide with a later test reusing the same
  `execution_id`. Added an autouse fixture that clears the singleton's
  stream-cleanup state after every test.

## [0.1.0] — 2026-09-06

### Added
- **19 built-in script templates** (api-health-check, disk-monitor,
  ssl-cert-check, port-check, dns-check, heartbeat, file-cleanup,
  db-vacuum, pg-backup, mysql-backup, s3-upload, csv-export,
  http-data-sync, db-query-report, email-report, slack-notify,
  telegram-notify, ntfy-notify, pushover-notify).
- **Script versioning** — every content change creates a version record;
  the full history is browsable and reversible from the UI.
- **Reliability controls** — per-script `retry_count`, `retry_delay`,
  `max_retry_window`, `prevent_overlap`.
- **Live log streaming over SSE** — execute and watch stdout/stderr
  appear in real time, including a LIVE indicator on running executions.
- **Artifact system** — scripts can call `save_artifact(name, bytes)` to
  upload files via the UI; up to 10 MB per file with disk-space guard.
- **Email alerting on failure** via configurable SMTP settings.
- **Auto-refresh dashboard** — counts and script list refresh on a
  scheduler that respects visible state.
- **Telegram/Slack/Discord webhook notifications** as script templates.
- **SSE done events with completion metadata** — duration, error message,
  final status.
- **Tests** — 705 passing across unit, integration, and PostgreSQL
  testcontainer suites (before F1-F3 additions).
- **Docker Compose production stack** — PostgreSQL 16 with daily backups
  at 2 AM, 7-day retention, automatic Alembic migrations on startup.
- **SQLite local-development mode** — `uv sync && alembic upgrade head && uvicorn`.
- **`cronator_lib`** — `get_logger()`, `save_artifact()`, `notify()`,
  `timer()`, `CronatorContext` with structured JSON logging inside
  Cronator and human-readable colored output locally.

### Security
- HTTP Basic Auth for all API endpoints and the UI.
- Sensitive settings (SMTP password, API keys) encrypted at rest with Fernet
  using `SECRET_KEY`.
- Input validation on cron expressions, timeouts, retry parameters.

### Changed
- The whole codebase is now Python 3.12 (was 3.11).

[Unreleased]: https://github.com/aa-blinov/cronator/compare/0.1.0...HEAD
[0.1.0]: https://github.com/aa-blinov/cronator/releases/tag/0.1.0
