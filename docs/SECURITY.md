# Security

This page is deliberately explicit about scope: what's actually enforced
today, versus what's a known, accepted gap. Treat every "not yet" below as
a real decision to make before exposing an instance beyond a trusted team.

## Authentication

HTTP Basic Auth (`verify_credentials`, `app/api/dependencies.py`) checked
against the `users` table first, falling back to `ADMIN_USERNAME`/
`ADMIN_PASSWORD` from the environment if the username isn't found in the
DB. A DB lookup exception also falls back to the env credentials, so a
transient DB issue doesn't lock out the one operator account that doesn't
depend on it.

All `/api/*` routes require authentication (enforced at router-include
level in `app/api/__init__.py`, not per-endpoint) except `/api/locale`
(needed by the unauthenticated login page for the language switcher) and
`/health` / `/metrics` (liveness/monitoring probes).

Passwords are hashed (`app/services/user_service.py`); the admin account is
seeded from `ADMIN_USERNAME`/`ADMIN_PASSWORD` on first startup if the
`users` table is empty.

Failed login attempts are rate-limited per username: 10 failures within 5
minutes locks that username out with `429` for the rest of the window,
even against the correct password (`check_login_lockout` /
`record_login_failure` in `app/api/rate_limit.py`, called from
`verify_credentials`).

**CSRF note for Basic Auth:** browsers auto-attach cached Basic Auth
credentials to any request to this app's origin, regardless of which page
triggered it — a form on an unrelated site could otherwise submit a
state-changing request here and have it silently authenticated.
`CsrfOriginGuardMiddleware` (`app/middleware/csrf_origin_guard.py`) blocks
`POST`/`PUT`/`PATCH`/`DELETE` requests whose `Origin` header doesn't match
this app's own origin. Requests with no `Origin` header at all (curl,
server-to-server API clients using Basic Auth directly) are left alone —
this targets the browser-credential-replay vector, not API automation.

## RBAC

Two roles exist: `admin` and `viewer`. **Viewers get read-only access;
every mutating action requires admin.** Enforced via `require_admin`
(`app/api/dependencies.py`), applied to every `POST`/`PUT`/`DELETE`
endpoint across scripts, executions, settings, and users, plus the three
HTML-page action routes (`/scripts/{id}/run`, `/executions/{id}/rerun`,
`/scripts/{id}/toggle`) that trigger the same mutations from the UI.

`require_admin` wraps `verify_credentials`: a username with no matching
`User` row (the legacy env-fallback account — only
`ADMIN_USERNAME`/`ADMIN_PASSWORD` can authenticate that way) is always
treated as admin, since that's the one account F21 seeds as admin in the
first place. A DB-backed user is only let through if `role == "admin"`;
anything else gets a `403`.

What a `viewer` **can** do: view scripts, executions, logs, live streams,
settings, diagnostics — anything behind a `GET`.

What a `viewer` **cannot** do: create/edit/delete/run/duplicate/revert a
script, cancel or delete an execution, change any setting, restore a
backup, or manage users. All of these return `403 Forbidden`.

The UI matches this: a `viewer` session doesn't render the "New Script"
nav link, action buttons (Run/Edit/Toggle/Delete/Duplicate/Revert/Cancel),
the bulk-action toolbar, or the settings maintenance controls — and the
script editor pages (`/scripts/new`, `/scripts/{id}/edit`) return `403`
outright rather than rendering an editor with no working Save button. A
`403` on a remaining HTML page route (e.g. a stale cached page, or a
direct URL) renders a proper error page instead of a raw JSON blob; API
calls still get plain JSON. `401` always keeps the default JSON handling
regardless of path — it carries the `WWW-Authenticate` header the browser
needs to show its native Basic Auth prompt, which an HTML error page
would silently break.

Tested with real HTTP Basic Auth against actual DB-backed viewer/admin
accounts in `tests/stateful/test_rbac_enforcement.py` — the rest of the
test suite uses a blanket auth override that always resolves as admin, so
it wouldn't have caught a gap here.

### User management

An admin manages accounts from `/users`: create, delete, change role, and
reset another user's password (`PATCH /api/users/{id}`). Deleting or
demoting the last remaining admin is blocked, so it's not possible to
lock every admin out of the instance through the UI. Any authenticated
user (admin or viewer) can change their own password from the "Change
password" link in the sidebar (`POST /api/users/me/password`), which
requires the current password. The one account this doesn't cover is the
legacy env-fallback admin (a username with no `User` row, authenticating
purely via `ADMIN_USERNAME`/`ADMIN_PASSWORD`) — that one's password is
only mutable by editing `.env` and restarting.

Every create/delete/role-change/password-reset action, and every
self-service password change, is recorded in `UserAuditLog` and readable
at `GET /api/users/audit` (admin-only, optionally filtered by
`target_username`, capped at 200 most recent entries by default) — who
changed what, and when. Shown as a "Recent Activity" table on the `/users`
page itself, refreshed after each action without a full page reload.

## Secrets at rest

`app/services/settings_service.py` encrypts a fixed set of sensitive keys
(`smtp_password`, `admin_password`, `webhook_url`) with Fernet before
writing them to the `settings` table. The key is derived from `SECRET_KEY`
(SHA-256 → URL-safe base64), so:

- `SECRET_KEY` must be set to a real random value — the app refuses to
  start on the `.env.example` placeholder (see
  [Configuration](CONFIGURATION.md#authentication-required)).
- **Changing `SECRET_KEY` after secrets have been saved makes them
  undecryptable** — `_decrypt()` degrades gracefully (logs a warning,
  returns the ciphertext as-is) rather than crashing, but you'll need to
  re-enter SMTP/webhook credentials through Settings afterward.
- `webhook_url` is encrypted because it typically carries an auth token
  directly in the path (Slack/Discord/Telegram webhook URLs all work this
  way) — leaving it in plaintext would be as bad as an unencrypted SMTP
  password. This was a real gap found and fixed during audit; if you're
  running a version from before that fix, upgrade before relying on
  webhook alerts for anything sensitive.

Non-sensitive settings (theme, locale, default timeout) are stored as
plaintext — there's nothing there worth encrypting, and it keeps them
directly queryable/editable for debugging.

## Script execution model

Read this before running anything you didn't write yourself, or before
treating multiple users' scripts as mutually untrusted.

- Each execution is a **real OS subprocess** (`asyncio.create_subprocess_exec`),
  running as the same OS user (`cronator`) as the app itself, with the same
  filesystem visibility.
- The child process gets a **minimal, explicit environment** — nothing
  from Cronator's own process environment is inherited (no ambient AWS
  credentials, no `DATABASE_URL`, nothing). Only `PATH`, `HOME`, `LANG`,
  `TZ`, Oracle client vars (for `cx_Oracle` support), Cronator's own
  `CRONATOR_*` context vars, and whatever the script explicitly declares in
  its `environment_vars` field are passed through.
- **There is no CPU or memory limit per script.** A script with a memory
  leak or an infinite loop can consume the container's entire CPU/memory
  budget, including what the Cronator process itself needs — a runaway
  script can degrade or crash the scheduler for every other script.
- **There is no filesystem or network sandboxing.** A script can read/write
  anywhere the `cronator` OS user can, and make arbitrary outbound network
  calls. Script content is stored as plain Python and is not statically
  vetted beyond a Ruff syntax/undefined-name check offered as a UI
  convenience (`POST /api/scripts/validate-script`) — it is not a security
  boundary.
- **`prevent_overlap` and `MIN_FREE_SPACE_MB`** (see
  [Operations](OPERATIONS.md)) are reliability features, not sandboxing —
  they stop the *scheduler* from making a bad situation worse, not a
  running script from causing one.

**Practical implication:** treat every script author as having the same
level of trust as the `cronator` OS user / container. This is a reasonable
model for "our team's own scripts, on our own server." It is not a
reasonable model for "let anyone on the team submit arbitrary scripts and
trust they won't affect each other," let alone multi-tenant SaaS.

## Transport & headers

Cronator does not terminate TLS — see
[Deployment → Reverse proxy](DEPLOYMENT.md#reverse-proxy--tls). Every
response carries HSTS, a restrictive `Content-Security-Policy`, and the
other OWASP baseline security headers via `SecurityHeadersMiddleware`,
registered before exception handlers so error responses get them too.

Static assets (CodeMirror, fonts) are self-hosted rather than loaded from a
CDN, so the CSP doesn't need to allow third-party script/style origins.

## Reporting

This is a self-hosted personal/small-team tool without a formal disclosure
program. If you find a real security issue, open an issue on the
repository or reach out to the maintainer directly rather than filing a
public issue with exploit details.
