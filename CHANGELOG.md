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
- **Playwright UI test infrastructure** — `tests/ui/` directory with shared
  fixtures (auth headers, browser context, screenshot helpers) and
  baseline screenshots of the four main pages.

### Fixed
- **Race condition in `_running_scripts`** — `ExecutorService` now discards
  the script from `_running_scripts` immediately after `_finish_execution`
  commits, instead of after the inner finally's 100ms SSE-friendly delay.
  Previously a freshly-finished script could not be deleted for ~100ms
  (responded 409) and a re-run was marked SKIPPED for the same window.

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
