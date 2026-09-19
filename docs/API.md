# API Reference

Every endpoint below requires HTTP Basic Auth
(`Authorization: Basic base64(username:password)`) except `/api/locale`,
`/health`, and `/metrics`. FastAPI also serves interactive docs at
`/docs` (Swagger UI) and `/redoc` — this page is a curl-first companion
to those, organized by resource with the "why" that isn't obvious from the
schema alone.

```bash
curl -u admin:password http://localhost:8080/api/scripts
```

## Scripts (`/api/scripts`)

| Method & Path | Purpose |
| --------------- | --------- |
| `GET /`                              | List scripts (paginated, `?enabled=`, `?search=` across name/description/cron/content) |
| `GET /{id}`                          | Full script detail, including `last_run_status`, `next_run_at`, `last_alert_at` |
| `POST /`                             | Create. If `path` is omitted, writes `content` to `scripts/<name>/script.py`; if `dependencies` is set, response's `needs_install: true` — call `POST /{id}/install` next |
| `PUT /{id}`                          | Update. Renaming, changing dependencies/python_version, or changing content/cron all have side effects — see below |
| `DELETE /{id}`                       | Blocked with `409` while the script is running |
| `POST /{id}/duplicate`               | Copies all editable fields, forces `enabled=false`, auto-suffixes the name (`-copy`, `-copy-2`, ...) |
| `POST /{id}/run`                     | Manual trigger (rate-limited: 5/min). Returns `execution_id` immediately — the run happens in the background |
| `POST /{id}/test`                    | Same as `/run` but marks the execution `is_test=true`; `409` if already running (rate-limited: 10/min) |
| `POST /{id}/rerun`                   | Same as `/run`, semantically "do it again" from the UI's history view |
| `POST /{id}/toggle`                  | Flip `enabled`, reschedules (or unschedules) the APScheduler job |
| `POST /{id}/rebuild-env`             | Recreates the venv from scratch (rate-limited: 3/min — expensive) |
| `POST /{id}/install`                 | Starts dependency installation in the background; stream its output via `GET /{id}/install-stream` (SSE) |
| `GET /{id}/packages`                 | Installed packages in the script's venv |
| `POST /validate-dependencies`        | Dry-run dependency resolution without saving |
| `POST /validate-script`              | Syntax check + Ruff (`E9,F63,F7,F82` only — undefined names, syntax errors) — a UI convenience, not a security boundary (see [Security](SECURITY.md#script-execution-model)) |
| `GET /{id}/versions` / `/{id}/versions/{n}` | Content history, deduplicated by hash — a save that doesn't change content/deps/python_version doesn't create a new version |
| `POST /{id}/revert/{version_number}` | Restores an old version's content/deps/cron/timeout and **reschedules the APScheduler job** if the cron expression changed |
| `GET /{id}/audit`                    | Field-level change log (old value → new value, who) |
| `POST /bulk/{action}`                | `action` is one of `enable`/`disable`/`delete`. Per-ID result (`succeeded`/`failed`) — never all-or-nothing, so one running script blocking a delete doesn't stop the rest |
| `GET /templates`                     | The 19 built-in templates (see the main [README](../README.md#templates)) |

**Side effects on `PUT /{id}`:** changing `cron_expression` or `enabled`
calls `scheduler_service.update_job()` (reschedules the live APScheduler
job). Changing `content`, `dependencies`, or `python_version` creates a new
`ScriptVersion` snapshot and sets `needs_install: true` in the response.
Changing `name` re-registers the script under the new name in
`environment_service`'s internal mapping. Every field change is recorded
in the audit log (`/api/scripts/{id}/audit`).

## Executions (`/api/executions`)

| Method & Path | Purpose |
| --------------- | --------- |
| `GET /`                                  | List (paginated, `?script_id=`, `?status=`, `?search=` across stdout/stderr/script name) |
| `GET /stats`                             | Aggregate counts + success rate + avg duration, optionally `?script_id=` scoped |
| `GET /{id}`                              | Detail; `?include_logs=false` omits stdout/stderr from the response |
| `GET /{id}/logs/{stdout\|stderr}`        | Plain text, `?tail_lines=N`, `?download=true` for a `Content-Disposition: attachment` response. Reads from the live in-memory buffer while the execution is running, falls back to the stored DB value otherwise |
| `GET /{id}/stream`                       | Server-Sent Events, live output while running. Supports `Last-Event-ID` for reconnect-and-resume |
| `POST /{id}/cancel`                      | Only works if the execution is still `RUNNING` and the app still holds a live process handle for it |
| `DELETE /{id}`                           | Blocked with `400` while `RUNNING` |
| `DELETE /` (bulk, age-based)             | `?days=30&script_id=` — deletes non-running executions older than N days |
| `GET /{id}/artifacts` / `/{id}/artifacts/{artifact_id}` | List / download a saved artifact file |
| `DELETE /{id}/artifacts/{artifact_id}`   | Also decrements the execution's `artifacts_count`/`artifacts_size_bytes` counters |

## Settings (`/api/settings`)

| Method & Path | Purpose |
| --------------- | --------- |
| `GET /`                          | Current non-sensitive settings (passwords/webhook URL are never returned in plaintext through this endpoint's response model) |
| `POST /update`                   | Partial update — only fields present in the body are changed. Writes to the DB (see [Configuration → Precedence](CONFIGURATION.md#precedence)), not `.env` |
| `GET /scheduler-status`          | APScheduler running state + job list |
| `POST /reload-scheduler`         | Rebuilds every job from the DB from scratch |
| `POST /test-email` / `/test-webhook` | Fire a test notification through the currently configured channel without waiting for a real failure |
| `GET /download-db`               | SQLite file download (dev only — no equivalent for PostgreSQL, use `pg_dump` instead) |
| `GET /artifacts-stats`           | Total artifact count/size + disk free/total on the artifacts volume |
| `GET /execution-stats`           | Execution counts by status + oldest record date, for the Settings page |
| `POST /cleanup-executions?days=N`| Manual age-based purge (1–3650 days), independent of the daily per-status cleanup job |
| `POST /clear-artifacts`          | Deletes **all** artifacts, DB rows and files — no undo |
| `GET /backups`                   | Lists `.sql.gz` files the `db-backup` service has produced |
| `POST /restore-backup`           | See [Operations → Restore](OPERATIONS.md#restore--via-the-ui-postapisettingsrestore-backup) for what this actually does under the hood — worth reading before relying on it |

## Users (`/api/users`) — admin only

| Method & Path | Purpose |
| --------------- | --------- |
| `GET /users`             | List. Any authenticated user can call this (see [Security → RBAC](SECURITY.md#rbac)) |
| `POST /users`            | Create; `409` if the username already exists, `422` if the password is under 8 characters |
| `DELETE /users/{id}`     | Blocked with `400` if it would delete the last remaining admin |

## Diagnostics & locale

| Method & Path | Auth | Purpose |
| --------------- | ------ | --------- |
| `GET /api/diagnostics` | required | See [Operations](OPERATIONS.md#health--diagnostics-endpoints) |
| `GET /api/locale` / `POST /api/locale` | none | UI language preference, persisted to Settings |
| `GET /api/locales`     | none | Supported locale codes |
| `GET /health`          | none | See [Operations](OPERATIONS.md#health--diagnostics-endpoints) |
| `GET /metrics`         | none | Prometheus exposition format |

## Common patterns

**Pagination**: `?page=1&per_page=20` (executions default to 50), response
shape is `{"items": [...], "total": N, "page": N, "per_page": N, "pages": N}`.

**Validation errors** return `422` with FastAPI's standard shape
(`{"detail": "Validation error", "errors": [...], "body": {...}}`) —
including for custom field validators (name length, cron expression
format) that raise a plain `ValueError`, which is a normal, expected `422`
and not a server error.

**Not-found** is consistently `404` with `{"detail": "... not found"}`
across resources.

```bash
# Create a script
curl -u admin:password -X POST http://localhost:8080/api/scripts \
  -H "Content-Type: application/json" \
  -d '{"name":"my-script","content":"print(1)","cron_expression":"0 * * * *"}'

# Watch it run live
curl -u admin:password -N http://localhost:8080/api/executions/1/stream

# Restore from a backup uploaded through the UI's file picker — via curl:
curl -u admin:password -X POST http://localhost:8080/api/settings/restore-backup \
  -F "file=@backups/cronator_20260125_020000.sql.gz"
```
