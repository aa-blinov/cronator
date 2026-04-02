# Agent Instructions

## Required Validation After Changes

After making code changes in this repository, always do all applicable steps below before wrapping up:

1. Run relevant tests.
2. Rebuild and restart Docker services when the change can affect the running app.
3. Check container status after restart.
4. If a container is not healthy, inspect logs before reporting completion.

## Test Commands

Use Docker-based tests by default.

Primary test command:

```powershell
npm run test:docker
```

Equivalent explicit command:

```powershell
docker compose -f docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from tests
```

This test flow uses:

- `docker-compose.test.yml`
- PostgreSQL test container `db-test`
- `tests` service built from Docker `target: builder` with `INSTALL_DEV=true`

Do not use the local `C:\Python312\python.exe` / `PYTHONPATH` workaround as the default validation path.
Only use local direct pytest as a temporary debugging fallback when Docker testing is not practical, and clearly say so.

Important:

- The Docker test command may print an orphan-container warning for the main app containers. That is expected in this repo.
- Do not add `--remove-orphans` to the Docker test command, because it can interfere with the running app stack.

## Docker Workflow

When changes touch templates, static assets, Docker files, startup behavior, runtime behavior, or anything user-visible in the app, run:

```powershell
docker compose -f docker-compose.yml up -d --build
```

Then always verify status:

```powershell
docker compose -f docker-compose.yml ps
```

If `cronator` is still in `health: starting`, wait briefly and check again.

If any container is unhealthy, restarting, or missing, inspect logs before finishing:

```powershell
docker compose -f docker-compose.yml logs --tail=100 cronator
docker compose -f docker-compose.yml logs --tail=100 db
```

## Completion Standard

Do not say the task is done until:

- the relevant tests pass, and
- `docker compose ps` shows the expected containers up, and
- `cronator` is healthy after rebuild when Docker was part of the change.
