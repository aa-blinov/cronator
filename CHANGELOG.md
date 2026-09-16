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
