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

## RBAC

Two roles exist: `admin` and `viewer`. **This is intentionally incomplete
scope, not a bug** — the RBAC test suite's own docstring says it outright:

> Full RBAC is out of scope for this release... The role gating on every
> endpoint is incremental — for now only admin can manage users; everyone
> else has the same access as before.

Concretely: `/api/users` (create/list/delete users) is admin-gated. Every
other endpoint — creating/editing/deleting scripts, running them,
restoring backups, deleting artifacts, clearing execution history, changing
SMTP/webhook settings — is available to any authenticated user, viewer or
admin. A `viewer` account today functions as a second admin account with a
different label.

If you need real per-role restrictions before that work lands, don't create
`viewer` accounts and expect them to be limited — they aren't.

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
