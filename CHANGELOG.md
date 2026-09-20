# Changelog

All notable changes to Cronator will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **P0 production-readiness batch: login lockout, CSRF-via-Basic-Auth
  guard, user-management audit log, automated backups.**
  - **Login lockout.** Failed Basic Auth attempts were never rate-limited
    (only expensive script operations were, `app/api/rate_limit.py`) — a
    password could be brute-forced with no throttling at all. Now 10
    failed attempts against one username within 5 minutes returns `429`
    for that username (`check_login_lockout`/`record_login_failure`,
    wired into `verify_credentials`), even if a later attempt uses the
    correct password.
  - **CSRF guard for Basic Auth.** Browsers auto-attach cached Basic Auth
    credentials to any same-origin request regardless of which page
    triggered it — a form on an attacker's site could submit a
    state-changing request here and have it silently authenticated.
    `CsrfOriginGuardMiddleware` (`app/middleware/csrf_origin_guard.py`)
    rejects `POST`/`PUT`/`PATCH`/`DELETE` requests whose `Origin` header
    doesn't match this app's own origin; requests with no `Origin` at all
    (curl, server-to-server API clients) are left alone. Accounts for
    `X-Forwarded-Proto` so it doesn't misfire behind a TLS-terminating
    reverse proxy.
  - **User-management audit log.** Create/delete/role-change/password-reset
    actions on other accounts, and self-service password changes, were
    never recorded anywhere — `ScriptAuditLog` is script-specific
    (`script_id` is a required FK). New `UserAuditLog` model +
    `GET /api/users/audit` (admin-only) answer "who changed whose role to
    admin" / "who reset whose password." Shown on the `/users` page as a
    "Recent Activity" table (color-coded by action, most recent first),
    refreshed after each action without a full page reload.
  - **App-level automated backup (secondary mechanism).** docker-compose
    deployments already get a real daily `pg_dump` via the `db-backup`
    sidecar (`docker-compose.yml`) — that one's the primary mechanism and
    is unaffected by this. It doesn't help a deployment that runs the
    `cronator` container on its own against an external/managed Postgres
    with no sidecar to add, so `BackupService`
    (`app/services/backup_service.py`) adds an in-app fallback: a daily
    gzipped backup at 02:00 UTC, off by default, opt-in per-deployment via
    the new "Automatic daily backup" toggle in Settings, keeping the 7
    most recent automated backups (never touches manually-made ones). It
    avoids shelling out to `pg_dump` — not on `PATH` in the runtime image,
    same constraint the existing restore-backup endpoint already works
    around — and instead drives the same asyncpg COPY protocol directly,
    producing a file in the exact format `POST /api/settings/restore-backup`
    already parses. Data-only (no schema), so it assumes a target with
    migrations already applied — unlike plain `pg_dump`, which dumps
    schema too. Verified as a real round-trip (create → wipe → restore)
    against PostgreSQL in `tests/pg/test_pg_auto_backup.py`. SQLite
    deployments (dev/test only) get a plain gzip of the `.db` file.
- **User management screen (`/users`) + password/role updates.** Admins
  previously could only create and delete users — changing an existing
  user's password or role meant deleting and recreating the account, and
  no one (including admins) could change their own password without
  editing `ADMIN_USERNAME`/`ADMIN_PASSWORD` in `.env` and restarting.
  Added `PATCH /api/users/{id}` (admin-only, password and/or role, blocks
  demoting the last remaining admin the same way deletion already blocks
  removing the last admin) and `POST /api/users/me/password`
  (self-service, any authenticated user, requires the current password).
  The new `/users` page (admin-only, linked from the sidebar) lists users
  with inline role change, password reset, and delete; every page's
  sidebar footer got a "Change password" link for self-service.
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

### Security
- **RBAC now actually restricts `viewer` accounts.** Previously only
  `/api/users` was admin-gated — a `viewer` had the same access as `admin`
  everywhere else. Added `require_admin` (`app/api/dependencies.py`,
  wraps `verify_credentials` with a role check) to every mutating
  endpoint across scripts, executions, settings, and the three HTML-page
  action routes (`run`, `rerun`, `toggle`). The UI now hides admin-only
  buttons/forms for a `viewer` session instead of rendering them and
  letting them 403; a 403 on any remaining HTML page route now renders a
  proper error page instead of a raw JSON blob (401 keeps its default
  JSON handling — it carries the `WWW-Authenticate` header the browser
  needs for its native Basic Auth prompt). Verified with real HTTP Basic
  Auth against actual DB-backed viewer/admin accounts, not the test
  suite's auth override (which always resolves as admin and couldn't
  have caught this).
- **`webhook_url` was stored in plaintext** in the `settings` table,
  unlike `smtp_password` — despite carrying an auth token directly in the
  path for Slack/Discord/Telegram webhooks. Added to `SENSITIVE_KEYS` so
  it's Fernet-encrypted at rest like every other credential.

### Changed
- **Removed the active-nav-item color accent entirely** (`.nav-link.active`,
  `app/static/input.css`) — first pass only dropped the tinted background
  fill and kept the left accent border; the ask was to remove the left-side
  color accent itself, so the rule is gone, no replacement indicator added.
- **CodeMirror syntax highlighting flashed in after a visible delay on
  the script editor.** Its `<script>` tags sit at the end of `<body>`
  (deliberately, so ~170KB of JS doesn't block first paint) — but on a
  large page the browser's preload scanner can't discover them until it's
  received that far into the document, so the code sat in plain,
  uncolored text for a beat before suddenly flashing into syntax-highlighted
  colors once the JS finally arrived. Added `<link rel="preload" as="script">`
  hints in `<head>` (`app/templates/script_editor.html`) so those files
  start downloading immediately, in parallel with the CSS — same
  execution point, just an earlier download start.
- **Disabled DaisyUI's button-pop animation and focus-shrink effect**
  (`--animation-btn`, `--animation-input`, `--btn-focus-scale` in the
  `dim` theme, `tailwind.config.js`) — every `.btn` across the app
  (Settings included) had a quarter-second "pop" on click and shrank
  slightly on focus; pure motion with no functional purpose.
- **Theme selector, version, and changelog link moved from the sidebar
  footer into Settings ("Appearance & About").** They cluttered the
  bottom-left of every single page for something a user touches rarely.
  Applying the persisted theme on page load no longer depends on the
  `<select>` itself being present (`app/static/app.js`) — it used to,
  which would have silently broken theme persistence on every page
  except Settings the moment the selector moved off them.
- **Script editor layout rebalanced.** The two-column layout (code+console
  on the left, settings on the right) let the settings column run far
  taller than the editor column, leaving several hundred pixels of empty
  space under the Output Console and burying the "Create Script"/"Save
  Changes" button at the bottom of whichever sidebar card was longest.
  Moved Dependencies and Environment Variables into the left column below
  the console (closer in height to the settings column now), and made
  the submit/cancel row a sticky bar pinned to the bottom of the
  viewport — it's now always reachable without scrolling to the very
  end. (Rebuilt `app/static/output.css` — Tailwind's classes are compiled
  at build time from the templates that reference them, so template-only
  changes referencing new utility classes silently do nothing until the
  CSS is rebuilt; `npm run build:css`.)

### Fixed
- **Sidebar didn't adapt to narrow viewports at all.** It was a fixed
  `w-64` flex child at every screen width, so on a phone or narrow
  window it just got clipped by the viewport instead of collapsing.
  Turned it into an off-canvas panel below the `lg` breakpoint (slides
  in as an overlay with a dismissible backdrop, toggled by a new
  hamburger button in the header) while staying exactly as it was —
  static, always visible — at `lg` and up. `app/templates/base.html`,
  `app/static/app.js` (`openSidebar`/`closeSidebar`), two new icons
  (`bars_3`, `x_mark_plain` in `icons.html`).
- **Full UI audit: rendering performance + visual consistency.**
  - **Version history diff viewer had the same "CodeMirror flash" bug
    just fixed in the script editor.** `script_version.html`'s two
    `<script>` tags sat mid-page with no preload hints, so a viewed
    version rendered as plain text before syntax highlighting suddenly
    kicked in. Added the same `<link rel="preload" as="script">` pair.
    Also switched its CodeMirror theme from `dracula` to `material-ocean`
    to match the editor — viewing a version and editing the same script
    one click apart showed two different color schemes for the same code.
  - **Half the app ignored the theme selector entirely.** `dashboard.html`
    and `script_detail.html` used raw Tailwind gray utilities
    (`text-gray-400`, `bg-gray-800`, `border-gray-700/50`, ...) exclusively;
    `scripts.html`, `executions.html`, `script_editor.html`,
    `script_version.html`, `users.html`, `execution_detail.html` were a
    mix. Switching away from the `dim` theme did nothing on those pages —
    they stayed the same dark grays no matter what was selected. Replaced
    every raw gray utility with the matching DaisyUI theme token
    (`text-base-content/60`, `bg-base-200`, `border-base-content/10`,
    etc.) across all 7 files (~60 occurrences). Also fixed a specific
    instance in `script_editor.html`'s cron-preview `.alert-info` box,
    which used `text-gray-900`/`text-gray-700` (dark text, correct only
    by accident against that particular alert color) — now
    `text-info-content` for a properly paired, theme-correct contrast.
  - **`/changelog` had a completely disconnected visual identity.** Being
    a raw `HTMLResponse` rather than a Jinja template, its inline
    `<style>` hardcoded hex colors (`#38bdf8`, `#1e293b`, `#020617`, ...)
    instead of reading the DaisyUI theme, and never loaded
    `/static/vendor/fonts/fonts.css`, so it silently fell back to system
    fonts instead of the app's Inter typeface. Swapped every hardcoded hex
    for the matching `oklch(var(--*))` theme variable and added the fonts
    stylesheet — selecting a different theme now actually changes this
    page too.
  - **`escapeHtml` was copy-pasted into 4 templates with behavioral
    drift.** `execution_detail.html` and `script_editor.html`'s copies
    skipped the `?? ''` null-guard that `settings.html` and `users.html`'s
    copies had, so `escapeHtml(null)`/`escapeHtml(undefined)` rendered the
    literal string `"undefined"` instead of an empty string. Consolidated
    into a single `window.escapeHtml` in `app/static/app.js`; deleted all
    4 inline copies.
  - **Dead code removed:** ~35 lines of unused `.toast`/`.toast-*`/
    `toast-pop` CSS in `app/static/input.css` (the real toast
    implementation in `app.js` never emits those classes — it builds
    elements with plain Tailwind utility classes and `data-testid="toast"`
    instead) and the matching dead `safelist` entries in
    `tailwind.config.js`; a `[data-confirm]` click handler in `app.js`
    that zero templates ever used (every destructive-action confirm is
    hand-rolled with a dynamic message instead).
- **Whole screen flashed to the wrong theme on every page load.** The
  saved theme (`localStorage`) was only applied by `app.js` at the end of
  `<body>` — the browser had already painted the server-rendered default
  theme by the time that script ran, so anyone using a non-default theme
  saw a visible flash on every navigation, worse on heavier pages like
  the script editor. Moved theme application into an inline, synchronous
  `<script>` at the very top of `<head>` (before any stylesheet) in
  `base.html` — blocking script execution means no frame paints before
  `data-theme` is correct. Every real page extends `base.html` except
  `/changelog`, which is a raw `HTMLResponse` outside the Jinja template
  system entirely and had no theme sync at all (always `dim`, hardcoded)
  — gave it its own copy of the same inline script for consistency.
- **Pages and static assets were transferred uncompressed with no cache
  headers at all** — the script editor's ~170KB HTML plus ~170KB
  CodeMirror JS plus ~105KB Tailwind CSS, in full, on every single
  navigation. Found live: a remote user reported `/scripts/new` "very
  slow to render" while the server itself answered in ~190ms — the whole
  cost was transfer size and zero reuse across page loads. Added
  `GZipMiddleware` (`app/main.py`) and a `CachedStaticFiles` wrapper that
  sets `Cache-Control: no-cache` on everything under `/static` — the
  browser still revalidates via the `ETag` `StaticFiles` already
  generates (a 304 costs almost nothing) rather than a fixed `max-age`,
  which would silently serve a stale asset for its whole duration after
  every deploy. Caught exactly that risk live while testing this same
  fix: an initial `max-age=86400` attempt made the very JS change under
  test invisible to a browser that had already loaded the page once.
- **`/changelog` rendered garbled, disconnected paragraphs instead of
  proper nested lists.** The page prefers the real `markdown` library and
  falls back to a tiny hand-rolled renderer if it isn't installed
  (`app/api/pages.py`) — except `markdown` was never actually declared as
  a project dependency anywhere, so every real deployment silently used
  the fallback, which has no support for indented sub-bullets or wrapped
  continuation lines (both of which this very CHANGELOG uses). Added
  `markdown>=3.6` to `pyproject.toml` — a pre-existing bug on the running
  production instance too, just never visually obvious until an entry
  complex enough to expose it (this one) got added.
- **A failed background dependency install after Create/Save silently
  redirected to the script detail page as if it had succeeded.**
  `POST /api/scripts/{id}/install-stream`'s `done` event hardcoded
  `{"success": true}` regardless of whether `pip`/`uv` actually installed
  the dependencies — `setup_environment_streaming`'s `finally` block put a
  bare `("done", "")` on the queue with no result attached, and the
  endpoint always translated that into `success: true`. The editor's own
  JS correctly branches on `data.success` to decide between navigating
  away and showing a retry button, but the field it trusted was never
  wired to the real outcome. Now the queue carries the actual result and
  the endpoint relays it. Found while checking production-readiness of the
  script editor's Create/Save flow end to end.
- **"Run Test" in the script editor never showed the script's actual
  output.** `/api/executions/{id}/stream` sends *named* SSE events
  (`event: stdout` / `stderr` / `done`) — the editor's console only had a
  bare `onmessage` handler, which never fires for named events, plus a
  `done` listener. Every line the script printed was silently dropped;
  the console only ever showed the synthetic "Test Started"/"Test
  Finished" markers, making the debug console useless for its actual
  purpose. Found while profiling the frontend — a chatty test script's
  output was conspicuously absent from a live capture. Added
  `stdout`/`stderr` listeners (`/api/scripts/{id}/install-stream`, a
  different endpoint used elsewhere in the same file, correctly sends
  unnamed events and was never affected). Also gave this console the
  same 2000-line sliding-window cap the execution detail page already
  had — it had no cap at all, so a genuinely chatty script would keep
  appending DOM nodes for as long as the tab stayed open.
- **"Run Test" on a brand-new script silently created and scheduled it.**
  The script editor's Run Test button auto-saves before every test run —
  necessary since a test execution needs a real script row — but for a
  never-before-saved draft it sent the "Run on schedule" toggle's value
  as-is, which defaults to checked. Clicking Run Test to try out a draft
  therefore created a live, `enabled=true`, cron-scheduled script before
  the user ever reviewed it or clicked the actual "Create Script" button;
  closing the tab without saving left a real script running on schedule
  with no explicit save action. Now every auto-save-before-test for a
  script that hasn't been explicitly saved forces `enabled: false`
  regardless of the toggle's visual state; the toggle's real value is
  only applied on an explicit "Create Script"/"Save Changes" click.
  Verified live end-to-end (test run → test run again → explicit save)
  against a disposable local instance via browser automation.
- **`restore-backup` hung forever on any real PostgreSQL backup.**
  `pg_dump`'s data section is `COPY ... FROM stdin`, not `INSERT`s — the
  previous `;`-based statement splitter tore the COPY header away from
  its data, and asyncpg sat waiting for COPY-protocol data that would
  never arrive, holding a pooled DB connection hostage. Also fixed:
  `pg_dump` always resets `search_path` to empty for the whole session
  (not just its own transaction), which — left unreset — rode back to
  the connection pool and broke the next unrelated request that reused
  it. Verified end-to-end against a real production backup file before
  writing the regression test.
- **`_run_script`'s error-recovery path could hang an execution at
  `RUNNING` forever.** If the retry inside the outer `except` block
  itself failed (e.g. the original failure was a DB commit, leaving the
  session needing a rollback before reuse), the second exception was
  uncaught — it skipped `close_stream()` and escaped as an unhandled
  exception in a fire-and-forget task. Since `cleanup_stale_executions`
  only runs once, at startup, the execution stayed stuck until the next
  restart.
- **`revert_to_version` didn't reschedule the APScheduler job.** Reverting
  a script to a version with a different `cron_expression` updated the
  DB row but left the live scheduler job running on the old schedule
  until some unrelated edit happened to touch it.
- **Custom pydantic validators crashed the 422 handler into a 500.** Any
  `field_validator` raising a plain `ValueError` (name length, cron
  format) produced an error dict with `ctx={"error": ValueError(...)}` —
  the raw exception object — which `JSONResponse` can't serialize.
  Wrapped `exc.errors()`/`exc.body` in `jsonable_encoder`.
- **`min_free_space_mb` was decorative** — shown in `/api/diagnostics`
  but never checked before starting an execution. Now enforced in
  `execute_script()`; a run below the threshold is refused with a
  visible `FAILED` execution instead of failing unpredictably wherever
  the next write happens to land. Fails open if free space can't be
  determined.
- **A success alert silently reset the failure-alert throttle window.**
  Both alert paths wrote to the same `last_alert_at` column; an
  unthrottled success alert could reset the 1-hour failure throttle,
  suppressing a genuine failure notification for a script that also
  happened to succeed once in between. Split into a dedicated
  `last_failure_alert_at` column (new migration) for the throttle gate.
- **HTTP access logs never reached `cronator.log` or the JSON format.**
  uvicorn's CLI configures `uvicorn`/`uvicorn.error`/`uvicorn.access`
  with their own handler and `propagate=False` before `app.main` is even
  imported. Repointed all three at the app's own handlers.
- **Docker container logs had no size cap.** None of the three services
  in `docker-compose.yml` had a `logging` block, so the default
  `json-file` driver kept every stdout line forever. Capped at 10MB×5
  (cronator/db) / 5MB×3 (db-backup).
- **`ScriptVersion.created_at` was missing `timezone=True`** — a
  model/schema drift from the actual `TIMESTAMPTZ` column that
  `alembic check` flags as a spurious pending migration. A stateless
  test now asserts every `DateTime` column in `Base.metadata` declares
  `timezone=True`.
- **`TIMEOUT` executions were never cleaned up** by the daily retention
  job — `RETENTION_BY_STATUS` was missing an entry for that status
  entirely, so timed-out executions accumulated without bound.

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
