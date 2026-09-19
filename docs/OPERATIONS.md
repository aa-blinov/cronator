# Operations

## Health & diagnostics endpoints

| Endpoint           | Auth | Purpose |
| -------------------- | ------ | --------- |
| `GET /health`       | none | Liveness/readiness probe. Checks DB connectivity, scheduler running state, disk free/total on the data directory, and Alembic current-vs-head revision (reports `"skipped"` when `SKIP_ALEMBIC_MIGRATIONS=1`, e.g. in tests). Returns `status: degraded` (not a 5xx) if a sub-check fails, so a load balancer's shallow "is it up" check and an operator's "what exactly is wrong" check can both use it. |
| `GET /metrics`      | none | Prometheus text exposition format — execution counts by status, running-execution gauge, scheduler job count, script totals, process uptime. |
| `GET /api/diagnostics` | required | A one-shot incident-triage snapshot: process RSS/uptime/thread count, DB table counts, scheduler job list, executor's running-process count, a masked config snapshot (secrets replaced with `***`), and log file size/rotation count. Use this over `/health` when you need to know *what state* the service is in, not just whether it's up. |

## Backups & restore

### Automated

The `db-backup` service (`docker-compose.yml`) runs a `pg_dump | gzip`
daily at ~02:00 (host clock), writing to `./backups/cronator_<timestamp>.sql.gz`
and deleting anything older than `BACKUP_RETENTION_DAYS` (default 7). This
is a shell loop, not app code — restarting `cronator` doesn't affect it.

### Manual backup

```bash
docker compose exec db pg_dump -U cronator cronator | gzip > backups/manual_$(date +%Y%m%d).sql.gz
```

### Restore — via the UI (`POST /api/settings/restore-backup`)

Upload a `.sql.gz` file (max 500MB) through **Settings → Restore Backup**.
The endpoint:

1. Decompresses and scans for a short list of catastrophic statements
   (`DROP DATABASE`, `DROP SCHEMA`, `TRUNCATE pg_catalog`) and refuses the
   whole file if any are present.
2. Parses the SQL statement-by-statement, with **`COPY ... FROM stdin`
   blocks handled specially** via `asyncpg`'s native COPY support — this
   matters because `pg_dump`'s data section is always COPY blocks, not
   `INSERT`s, and a naive `;`-based split tears a COPY header away from its
   data. (This was a real bug, found and fixed by uploading an actual
   production backup to a throwaway PostgreSQL container and watching
   `pg_stat_activity` show the connection stuck forever waiting for COPY
   data that would never arrive — see the git history for
   `app/api/settings.py` if you want the full writeup.)
3. **Resets `search_path`** on the connection before it returns to the
   pool. `pg_dump` always opens with
   `SELECT pg_catalog.set_config('search_path', '', false)` — session-scoped,
   not transaction-scoped — and without an explicit reset, that empty
   search_path would ride back to the pool and break the *next* unrelated
   request that happened to reuse the same connection (`relation "..." does
   not exist` on a perfectly normal unqualified query).
4. Each statement commits independently; a failed statement is logged and
   skipped, not fatal to the whole restore. The response reports
   `statements_applied`, `statements_failed`, and `rows_restored` — check
   `statements_failed == 0` before trusting a restore actually completed.

### Restore — manually, via CLI

```bash
docker compose stop cronator
gunzip < backups/cronator_20260125_020000.sql.gz | docker compose exec -T db psql -U cronator cronator
docker compose start cronator
```

This uses `psql` directly and doesn't have the COPY-block or search_path
concerns above (those are specific to the app's own text()-based restore
path) — prefer this for anything beyond "restore this one backup file
through the UI."

**Either way, restoring in-flight execution state is not meaningful** — a
script that was `RUNNING` at backup time will still show as `RUNNING` after
restore, with no subprocess actually attached to it. Cancel or manually
correct such rows after a restore.

## Execution retention

`cleanup_service.cleanup_by_status()` runs daily at 03:00 UTC (an internal
APScheduler job, not the Postgres backup service) and keeps, per script ×
status:

| Status      | Kept |
| ------------ | ------ |
| `SUCCESS`    | 200 most recent |
| `FAILED`     | 500 most recent |
| `TIMEOUT`    | 500 most recent |
| `SKIPPED`    | 100 most recent |
| `CANCELLED`  | 100 most recent |

Anything beyond those counts is deleted along with its artifact directory
on disk. There's also an age-based cleanup
(`POST /api/settings/cleanup-executions?days=N`) for a manual one-off
purge independent of the per-status counts.

## Disk space

`MIN_FREE_SPACE_MB` (default 100MB, see [Configuration](CONFIGURATION.md))
is checked before every new execution starts
(`executor_service._get_free_space_mb`, checked against the volume holding
`artifacts_dir`, falling back to `data_dir`). Below the threshold, the run
is refused and a `FAILED` execution is created with a clear
`error_message` instead of the run starting and failing unpredictably
partway through wherever the next write happens to land.

If the check itself can't determine free space (permission error, missing
mount), it **fails open** — an unrelated filesystem hiccup shouldn't stop
every script from ever running again.

This check only covers *starting a new run*. It does not stop a
long-running script from filling the disk with its own output or
artifacts mid-execution — see
[Security → Script execution model](SECURITY.md#script-execution-model).

## Alerting

Alerts fire per-script based on `alert_on_failure` / `alert_on_success`,
via email (SMTP) and/or a configured webhook URL (`POST` with a JSON
payload — see `app/services/alerting.py::send_webhook`).

- **Failure alerts are throttled to once per hour per script**
  (`Script.last_failure_alert_at`). This is a dedicated column, separate
  from `Script.last_alert_at` (the "last alert of any kind" field the UI
  displays) — they used to share one column, which meant an *unthrottled*
  success alert would reset the *failure*-alert throttle window: a script
  failing at 09:00 (alert sent), succeeding at 10:30 (alert sent,
  overwrites the shared timestamp), failing again at 10:35 would get
  silently suppressed even though the last failure alert was 1h35m
  earlier. Fixed; kept here because it's exactly the kind of alerting bug
  that's invisible until you're staring at a script that's been broken for
  a day with zero notifications.
- **Success alerts are never throttled** — every successful run with
  `alert_on_success=True` sends one. This is by design (success alerts are
  opt-in and presumably wanted every time), not an oversight.
- **Manual notifications** (`cronator_lib.notify()` called from inside a
  script) go out immediately, independent of the above throttling.

Test the current SMTP config and webhook URL from **Settings**
(`POST /api/settings/test-email`, `POST /api/settings/test-webhook`)
without waiting for a real failure.

## Troubleshooting

**An execution is stuck at `RUNNING` and nothing is happening.**
`executor_service.cleanup_stale_executions()` only runs once, at app
startup — it does not poll periodically. If an execution got stuck (e.g.
an unhandled exception during finalization, or the container was killed
mid-run), it stays `RUNNING` in the DB until the next restart. A restart
will mark stale `RUNNING` rows as failed; if you can't restart right now,
correct the row manually or use `POST /api/executions/{id}/cancel` (only
works if the app still has a live process handle for it — won't help after
a container restart severed that link).

**Logs aren't showing up in `cronator.log` / aren't JSON despite
`LOG_FORMAT=json`.** Check whether this is actually an HTTP access line —
those are uvicorn's own `uvicorn.access` logger, repointed at the app's
handlers at import time in `app/main.py`. If you're running the app some
other way than `uvicorn app.main:app` (the Dockerfile's `CMD`), verify that
code path still executes before uvicorn starts serving.

**Restore says `success: true` but data looks incomplete.** Check
`statements_failed` in the response — a restore doesn't fail the whole
request just because some individual statements didn't apply (e.g. a
constraint that already exists). `rows_restored` gives you the actual COPY
row count to cross-check against what you expect from the source dump.

**A script's cron schedule changed in the UI but it's still running on the
old schedule.** Every code path that changes `cron_expression` or
`enabled` must call `scheduler_service.update_job()` — if you're running a
modified/older version of the app, check that reverting to a previous
script version also does this (it does as of the current codebase; this
was a real bug found during audit — see `app/api/scripts.py`'s
`revert_to_version`).
