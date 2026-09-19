# Deployment

## Production: Docker Compose

```bash
git clone https://github.com/aa-blinov/cronator.git
cd cronator
cp .env.example .env
# set ADMIN_PASSWORD, SECRET_KEY, POSTGRES_PASSWORD in .env — see
# CONFIGURATION.md for what each one does and why the app refuses to
# start on the placeholder values

docker compose up -d
```

`docker compose up -d` brings up three services:

| Service    | Image                | Role |
| ----------- | --------------------- | ------ |
| `db`        | `postgres:16-alpine`  | Not exposed to the host (no `ports:` mapping) — reachable only from `cronator-network` |
| `cronator`  | built from `Dockerfile` | The app itself; waits for `db`'s healthcheck before starting |
| `db-backup` | `postgres:16-alpine`  | A shell loop that `pg_dump`s daily at ~02:00 and prunes backups older than `BACKUP_RETENTION_DAYS` |

Alembic migrations run automatically as part of the app's startup
(`lifespan` in `app/main.py`), before uvicorn starts accepting connections
— so the container healthcheck passing already implies migrations
succeeded.

## Reverse proxy / TLS

Cronator doesn't terminate TLS itself. Put it behind nginx, Caddy, or
Traefik, and forward to `http://<host>:${PORT}`. The app already sets HSTS
and a restrictive CSP via `SecurityHeadersMiddleware`, so once TLS is
terminated upstream, no further header configuration is needed on the proxy
side for those.

## Log rotation

Two independent layers are capped, and both need attention if you change
how logging is configured:

1. **`cronator.log`** (`RotatingFileHandler`, `app/main.py`) — 10MB × 5
   backups, 60MB max. Bind-mounted to `./logs` on the host.
2. **Container stdout** (`docker-compose.yml`'s `logging:` block per
   service) — `json-file` driver, capped at 10MB × 5 files for `cronator`
   and `db`, 5MB × 3 for `db-backup`. Without this, Docker's default
   json-file driver has **no size cap at all**, and
   `/var/lib/docker/containers/<id>/<id>-json.log` on the host grows
   unbounded — this got more relevant once uvicorn's access logs were
   repointed at the same handlers as the rest of the app (see
   [Configuration → Logging](CONFIGURATION.md#logging)), since that's more
   volume flowing to stdout than before.

A test (`tests/stateless/test_dockerfile_lint.py::test_all_services_cap_container_log_growth`)
asserts every service in `docker-compose.yml` has a `logging` block with
`max-size` set, so a future service added without one fails CI locally
(it's skipped inside the Docker test container itself, since
`docker-compose.yml` is excluded from the build context by `.dockerignore`
— run `pytest tests/stateless/ -v` on the host to exercise it).

## Resource sizing

- **PostgreSQL**: ships with defaults (`max_connections=100`,
  `shared_buffers=128MB`). The app's own pool caps out at 30 connections
  (`DB_POOL_SIZE` + `DB_MAX_OVERFLOW`), leaving headroom for manual
  `psql` access or a second reader. `data_checksums` is off by default
  (the postgres image's own default) — enabling it requires re-initializing
  the data directory (`--data-checksums` at `initdb` time), so it can't be
  turned on after the fact without a dump/restore.
- **Disk**: `MIN_FREE_SPACE_MB` (default 100MB) gates new script
  executions — see [Operations → Disk space](OPERATIONS.md#disk-space).
  Size the `data`/`envs`/`scripts` volumes for your actual workload: every
  script gets its own virtualenv (tens of MB each), and artifacts +
  execution history accumulate until the daily cleanup job prunes them
  (see [Operations → Retention](OPERATIONS.md#execution-retention)).
- **CPU/memory**: no per-script resource limits exist yet — every script's
  subprocess can use as much CPU/memory as the container has. See
  [Security → Script execution model](SECURITY.md#script-execution-model)
  before running untrusted or unbounded scripts on a shared host.

## Upgrades

```bash
git pull
docker compose up -d --build
```

Migrations run automatically on the new container's startup. There is no
zero-downtime rolling upgrade path — `docker compose up -d --build`
recreates the `cronator` container, so in-flight executions are interrupted
(the container's `CMD exec uvicorn ...` means SIGTERM reaches uvicorn
directly, which runs the FastAPI lifespan shutdown — but a running script
subprocess isn't automatically resumed after restart, and its execution
record needs to be checked/re-run manually if the app didn't get to mark
it finished before shutdown completed).

## Scaling limits

Cronator is designed to run as a single process. Things that would break if
you ran two instances against the same database:

- **APScheduler jobs**: each instance would independently fire every
  enabled script on its own schedule — no leader election, no distributed
  lock across instances (the per-script `asyncio.Lock` in
  `executor_service` only prevents overlap *within one process*).
- **In-memory SSE state**: live log streaming state
  (`ExecutionStreamState`) lives in the process that ran the script; a
  second instance's `/stream` endpoint wouldn't have it and would fall back
  to stored (non-live) output.
- **Install queues**: `environment_service.install_queues` (for streaming
  dependency-install logs) is per-process in-memory state too.

If you need more throughput than one instance provides, the honest answer
today is a bigger single instance, not horizontal scaling — see
[Architecture](ARCHITECTURE.md) for why (no queue/broker, no distributed
state by design).
