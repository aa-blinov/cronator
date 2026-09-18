# Agent Instructions

## Required Validation After Changes

After making code changes in this repository, always do all applicable steps below before wrapping up:

1. Run relevant tests.
2. Rebuild and restart Docker services when the change can affect the running app.
3. Check container status after restart.
4. If a container is not healthy, inspect logs before reporting completion.
5. **Run `uv run ruff check app/ tests/` and confirm "All checks passed!" before claiming done.** CI's `Lint (ruff)` job runs ruff on every push and will block the merge if there are F401/F841/E501/E402 errors. Fix the lint errors in the same commit as the code change — do not leave them for the next agent.
6. **Verify the live app responds** to any changed endpoint via `curl -u admin:admin http://localhost:8080/<path>`. A passing pytest doesn't prove the FastAPI app actually serves the new route without an `UnboundLocalError` or a missing import.
7. **Check `git status` is clean** before reporting completion. Unstaged changes mean half-finished work.
8. **Run `gh run list --limit 5` after `git push`** to confirm CI passed on the actual remote — local green does not equal remote green (CI uses different actions, secrets, OS).

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
- **The test container caches source code in its image. After editing any `app/**/*.py`, `tests/**/*.py`, or `Dockerfile`, run `docker compose -f docker-compose.test.yml build tests` before `docker compose ... run --rm tests`** — otherwise the test container will run the OLD code and tests will pass against the wrong version.

### Async test gotchas

- When a test triggers a script run (`POST /api/scripts/{id}/run`) and then immediately tries a guarded action (delete / install / rebuild-env), **never use a flat `await asyncio.sleep(N)`**. CI runners are slower than local machines; the script may not have entered the running state when you assert on it, or it may already have finished, and the test will be flaky.
  - Use a polling helper that checks `last_run_status` on `/api/scripts/{id}` until the desired value is observed, with a generous timeout.
  - When polling for a "terminal" state, never use `want_status=None` to mean "any non-running" — `None == None` is True and the poll returns immediately on the first iteration.
  - Use an explicit set of terminal statuses (`{"succeeded", "failed", "cancelled", "timeout", "skipped"}`).

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

## CI Workflow Gotchas

`.github/workflows/ci.yml` runs six jobs on every push. To avoid a red CI:

- **Lint (ruff)**: ruff defaults to `select = ["E", "F", "I", "UP"]`. The `tests/**` ignore in `pyproject.toml` only covers E501 (line length) — F401/F841/F541 still fire on test files. Keep test imports tidy.
- **Docker compose validate**: `docker compose ... config --quiet` exits 1 if `env_file: .env` is referenced and the file is missing. CI's `docker-validate` step stubs `.env` from `.env.example` + `BACKUP_RETENTION_DAYS=7` before running the validate — **do not remove that step** without providing `.env` another way.
- **Dockerfile lint (hadolint)**: pinned to commit `08b13a8fc994e434ccaaff93a72f1842dc4c4d11`. Tags like `@v3` are not guaranteed to exist for this community action — pin to a commit SHA.
- **Tests (Docker)**: same caching rule as the local test command — the image holds the code, so rebuild before re-running.
- **Tests (PostgreSQL)**: runs `tests/pg/` only, against a service-container `postgres:16-alpine`. No alembic, uses `SKIP_ALEMBIC_MIGRATIONS=1`.
- **Type check (mypy)**: marked `continue-on-error: true` — it's opt-in and not a gate.

After `git push`, verify with:

```bash
gh run list --limit 5 --json databaseId,conclusion,name,event,headBranch
gh api repos/<owner>/<repo>/actions/runs/<id>/jobs
```

If a job failed, fetch its logs:

```bash
JOB_ID=$(gh api repos/<owner>/<repo>/actions/runs/<id>/jobs | jq '.jobs[] | select(.conclusion=="failure") | .id' | head -1)
gh api repos/<owner>/<repo>/actions/jobs/$JOB_ID/logs
```

## Live Smoke After Backend Changes

After any change to `app/api/**/*.py` or `app/services/**/*.py`, hit the affected endpoint on the live container before claiming done. The pytest suite uses an ASGITransport that bypasses some real-server concerns (e.g. middleware order, response model validation, `request.app.state` setup):

```bash
curl -s -o /dev/null -w "%{http_code}\n" -u admin:admin http://localhost:8080/api/<path>
curl -s -u admin:admin http://localhost:8080/api/<path> | python3 -m json.tool
```

If the response is 500, inspect logs immediately:

```bash
docker compose -f docker-compose.yml logs --tail=50 cronator
```

## UI Tests (Playwright)

Playwright tests in `tests/ui/` run against the **live stack** at `http://localhost:8080`, not inside the Docker test container. They are excluded from `pyproject.toml`'s `testpaths` so the Docker `npm run test:docker` flow never tries to collect them.

Host prerequisites:

- `uv pip install playwright==1.49.0` (newer versions refuse to download Chromium on this OS)
- `playwright install chromium` (downloads headless shell 1148)

Run:

```bash
uv run pytest tests/ui/ -v
```

The shared conftest in `tests/ui/conftest.py` skips the whole module silently if Playwright is not importable.

## Completion Standard

Do not say the task is done until:

- the relevant tests pass (Docker pytest + `uv run ruff check app/ tests/`),
- `docker compose ps` shows the expected containers up,
- `cronator` is healthy after rebuild when Docker was part of the change,
- the live app responds with 200 on every changed/added endpoint,
- `git status` shows a clean working tree,
- (after `git push`) `gh run list` shows the CI run for the new SHA as green.
