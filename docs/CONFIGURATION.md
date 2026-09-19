# Configuration

Cronator reads settings from environment variables (`.env` locally, `env_file`
in `docker-compose.yml`) at startup via `app/config.py`
(`pydantic-settings`). A subset of those are then **copied into the
database** on first run and become editable from **Settings → Edit
Settings** in the UI without a restart — see [Precedence](#precedence)
below for exactly which ones and why that matters.

## Environment variables

### Application

| Variable    | Default   | Notes                                              |
| ----------- | --------- | --------------------------------------------------- |
| `APP_NAME`  | `Cronator`| Shown in the UI header and health check response    |
| `DEBUG`     | `false`   | Enables SQLAlchemy `echo` (verbose SQL logging)      |
| `HOST`      | `0.0.0.0` | Bind address (Dockerfile's `CMD` reads `$PORT`, not this — `HOST` is informational for local `uvicorn` runs) |
| `PORT`      | `8080`    | Used by the Dockerfile's `CMD`, the container healthcheck, and `docker-compose.yml`'s port mapping — change it in one place (`.env`) and it propagates everywhere |

### Authentication (required)

| Variable         | Default | Notes                                                                 |
| ---------------- | ------- | ------------------------------------------------------------------------ |
| `ADMIN_USERNAME` | `admin` | Seeded as the first admin user on first startup if the `users` table is empty |
| `ADMIN_PASSWORD` | *none*  | **Required.** Startup fails hard if left at the `.env.example` placeholder value — a warning would be too easy to miss in container logs, and a weak/default admin password on an internet-facing instance is exactly the kind of mistake worth blocking on |
| `SECRET_KEY`     | *none*  | **Required.** Derives the Fernet key that encrypts sensitive settings at rest (SMTP password, webhook URL — see [Security](SECURITY.md#secrets-at-rest)). Also hard-fails on the placeholder value for the same reason. **Changing it after settings have been saved makes those encrypted values undecryptable** — the app degrades gracefully (returns the ciphertext as-is with a warning logged) rather than crashing, but you'll need to re-enter SMTP/webhook credentials. |

### Database

| Variable                | Default                                        | Notes |
| ------------------------ | ----------------------------------------------- | ------- |
| `DATABASE_URL`           | `sqlite+aiosqlite:///./data/cronator.db`        | `docker-compose.yml`'s `environment:` block always overrides this to point at the `db` service, regardless of what's in `.env` — see [Precedence](#precedence) |
| `POSTGRES_PASSWORD`      | *none* (Docker only)                            | Consumed by `docker-compose.yml` for both the `db` service and to build `DATABASE_URL` for the `cronator` service |
| `DB_POOL_SIZE`           | `20`                                            | Ignored for SQLite. 20 + `DB_MAX_OVERFLOW` (10) = 30 max connections from one app instance — comfortably under PostgreSQL's default `max_connections=100` |
| `DB_MAX_OVERFLOW`        | `10`                                            | |
| `DB_POOL_TIMEOUT`        | `30` (seconds)                                  | How long a request waits for a free pooled connection before raising |
| `DB_POOL_RECYCLE`        | `3600` (seconds)                                | Connections older than this are discarded and replaced — guards against a database-side idle-connection timeout killing a connection the pool doesn't know is dead |
| `DB_POOL_PRE_PING`       | `true`                                          | Cheap `SELECT 1` before handing out a pooled connection, to catch ones the DB already closed |

### Directories

| Variable      | Default             | Notes |
| ------------- | -------------------- | ------- |
| `SCRIPTS_DIR` | `./scripts`          | Relative paths are resolved against the app's `base_dir` (repo root in dev, `/app` in the container) |
| `ENVS_DIR`    | `./envs`             | Per-script `uv` virtualenvs live here |
| `LOGS_DIR`    | `./logs`             | `cronator.log` (rotating, 10MB × 5 backups) |
| `DATA_DIR`    | `./data`             | SQLite DB file (dev only) and the parent of `artifacts_dir` |

`ensure_directories()` creates all of these on startup and logs a warning
(doesn't crash) if it can't — useful when a bind-mounted host directory
has unexpected permissions.

### Execution & artifacts

| Variable                | Default | Notes |
| ------------------------ | ------- | ------- |
| `DEFAULT_TIMEOUT`        | `3600`  | Seconds; per-script `timeout` overrides this at creation time |
| `MAX_LOG_SIZE`           | `1000000` (1MB) | stdout/stderr are truncated past this size before being stored |
| `MAX_ARTIFACT_SIZE_MB`   | `10`    | Per-file cap enforced by `cronator_lib.save_artifact()` |
| `MIN_FREE_SPACE_MB`      | `100`   | Enforced before starting a new execution (`executor_service._get_free_space_mb`) — a run below this threshold is refused with a visible `FAILED` execution rather than failing unpredictably wherever the next write happens to land. See [Operations → Disk space](OPERATIONS.md#disk-space). |
| `MAX_FILENAME_LENGTH`    | `200`   | |

### SMTP (alerts)

| Variable        | Default | Notes |
| ---------------- | ------- | ------- |
| `SMTP_ENABLED`   | `false` | |
| `SMTP_HOST`      | `""`    | |
| `SMTP_PORT`      | `587`   | `465` uses direct SSL, anything else uses STARTTLS |
| `SMTP_USER`      | `""`    | |
| `SMTP_PASSWORD`  | `""`    | Encrypted at rest once saved through Settings — see [Security](SECURITY.md#secrets-at-rest) |
| `SMTP_FROM`      | `""`    | Falls back to `SMTP_USER` if empty |
| `ALERT_EMAIL`    | `""`    | Recipient for failure/success alerts |

### Logging

| Variable     | Default | Notes |
| ------------- | ------- | ------- |
| `LOG_FORMAT`  | `human` | `json` switches to one structured JSON object per line (`app/services/json_logging.py`) — recommended for log aggregators |
| `LOG_LEVEL`   | `INFO`  | Standard Python logging level names |

uvicorn's own access/error loggers are repointed at the same handlers as
the rest of the app at import time (`app/main.py`) — without this, HTTP
access lines never reached `cronator.log` or the JSON format regardless of
`LOG_FORMAT`, since uvicorn's CLI configures those loggers with
`propagate=False` before the app module is even imported.

### Docker Compose only (not read by the app)

| Variable                 | Default | Used by |
| -------------------------- | ------- | --------- |
| `BACKUP_RETENTION_DAYS`   | `7`     | The `db-backup` service's cleanup loop (`find ... -mtime +N -delete`) — this is a shell script, not app code, so changing it doesn't need a restart of `cronator` itself |

## Precedence

Two independent layers exist, and they resolve differently:

1. **Environment variables → `Settings` object** (`app/config.py`). Read
   once at process start. `ADMIN_PASSWORD`/`SECRET_KEY` are env-only —
   there is no UI to change them, on purpose (rotating `SECRET_KEY` breaks
   decryption of already-stored secrets, so it shouldn't be a casual
   button click).
2. **Database-backed settings** (`app/services/settings_service.py`,
   `Setting` table). `SettingsService.get(key, default)` checks the DB
   first, falling back to the matching `Settings` attribute (same name) if
   the key was never saved to the DB. `POST /api/settings/update` writes
   here, not to `.env` — changes apply immediately, no restart.

**`.env` seeds the initial values; after the first save through the UI, the
database wins** for everything in that second layer (SMTP config, webhook
URL, theme, locale, default timeout). If you edit `.env` after the fact
expecting it to change already-saved settings, it won't — go through
Settings instead, or delete the corresponding row from the `settings` table
to fall back to the env value again.

`DATABASE_URL` is a partial exception: `docker-compose.yml`'s own
`environment:` block for the `cronator` service always overrides whatever's
in `.env`, so switching between SQLite (local dev) and PostgreSQL (Docker)
happens automatically based on *how* you run the app, not by editing
`DATABASE_URL` yourself.
