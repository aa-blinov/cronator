# Development

## Setup

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # if you don't have uv
uv sync --all-extras
uv run alembic upgrade head
uv run python -m uvicorn app.main:app --reload --port 8080
```

Local dev uses SQLite by default (`DATABASE_URL` in `.env` /
`app/config.py`) — no database server to stand up.

## Test structure

```
tests/
├── conftest.py         # env vars + event loop only, shared by both dirs below
├── stateless/          # pure unit tests: no DB, no test_client
│   └── services/       # ExecutorService, scheduler, alerting, retries — all mocked
├── stateful/           # conftest.py has the DB fixtures (test_engine, db_session,
│                       # test_client, script_factory, execution_factory, ...)
├── pg/                 # a subset of stateful tests re-run against real PostgreSQL
│                       # (testcontainers, or TEST_DATABASE_URL in CI) — catches
│                       # SQLite-only assumptions (COPY protocol, search_path, etc.)
└── ui/                 # Playwright end-to-end flows with baseline screenshots
```

`tests/stateless` and `tests/stateful` are split by **actual fixture
usage**, not by folder convention — a test that doesn't touch `db_session`/
`test_client`/any DB-backed fixture belongs in `stateless`, full stop. This
matters because `tests/pg/` is a *sibling* of `tests/stateful/`, not a
descendant — pytest's `conftest.py` lookup only walks up a test file's own
directory tree, so `tests/pg/conftest.py` has to explicitly re-export the
fixtures it needs from `tests/stateful/conftest.py` (an ordinary import;
pytest discovers fixtures by scanning a conftest module's namespace, not by
where they were originally defined). If you add a new DB fixture to
`tests/stateful/conftest.py` that `tests/pg/` tests should also use, add it
to that re-export list too — this exact thing broke silently once (all 36
`tests/pg/` tests, "fixture not found") because it isn't covered by the
default `pytest tests/stateless tests/stateful` run.

### Running tests

```bash
# Fast path — SQLite, no Docker
uv run pytest tests/stateless tests/stateful -v

# Against real PostgreSQL (needs Docker for testcontainers, or set
# TEST_DATABASE_URL yourself)
uv run pytest tests/pg/ -v

# Full Docker-based run (what CI's "Tests (Docker)" job does)
docker compose -f docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from tests
```

A handful of tests in `tests/stateless/test_dockerfile_lint.py` and
`test_ci_workflow.py` need the actual `Dockerfile`/`docker-compose.yml`
files at their expected host paths — they auto-skip
(`_skip_if_not_on_host()`) when run inside the Docker test container, since
those files are excluded from the build context by `.dockerignore`. Run
`pytest tests/stateless/ -v` directly on the host to exercise them.

### Writing tests

- Prefer a real bug over a coverage number. A test that doesn't fail
  without the fix it's paired with isn't proving anything — when in doubt,
  `git stash` the fix and confirm the test actually goes red.
- `MagicMock(name="x", ...)` does **not** set a `.name` attribute (`name`
  is reserved for the mock's repr) — set it explicitly after construction
  if a test needs `.name` to mean something.
- The `event_loop` fixture (root `conftest.py`) is session-scoped —
  intentional, don't "fix" it per-test without checking why first (there's
  an `autouse` fixture in `tests/stateful/conftest.py` that resets
  `executor_service`'s stream-cleanup state between tests specifically to
  work around cross-test task leakage this causes).
- If a test needs two DB sessions that must see each other's committed
  writes (e.g. verifying state after a background task ran), grab a fresh
  session from `test_engine` via `async_sessionmaker(test_engine, ...)`
  rather than reusing the `db_session` fixture from both sides — SQLite's
  `aiosqlite` driver can raise `MissingGreenlet` when the shared session
  object is touched concurrently from two different code paths.

## Migrations

```bash
uv run alembic revision --autogenerate -m "describe the change"
uv run alembic upgrade head
uv run alembic downgrade -1     # roll back one step
uv run alembic check            # fails if models and the DB schema disagree
```

`alembic check` needs a real database connection (it diffs the live schema
against `Base.metadata`) — point `DATABASE_URL` at a scratch PostgreSQL
instance before running it; it won't catch anything meaningful against a
freshly-created SQLite dev DB you just migrated yourself.

**Every `DateTime` column must declare `timezone=True`.** The whole app
works in UTC-aware datetimes; a bare `DateTime()` column drifts silently
from the actual PostgreSQL `TIMESTAMPTZ` column type and `alembic check`
will flag it as a spurious pending migration. This is enforced by a
stateless test (`tests/stateless/test_model_timezone_consistency.py`) that
checks every column in `Base.metadata` without needing a live database.

## Linting & formatting

```bash
uv run ruff check .      # E, F, I, UP rule sets, line-length 100
uv run ruff format .
uv run mypy app/         # CI runs this too
```

`tests/**` and `app/script_templates.py` are exempt from the line-length
rule (`E501`) — test docstrings in Russian and template source-as-string
literals both legitimately run long.

## Project layout

```
app/
├── api/            # FastAPI routers — one module per resource
├── services/       # business logic: executor, scheduler, environment,
│                   # alerting, settings_service, cleanup_service
├── models/         # SQLAlchemy models
├── schemas/        # Pydantic request/response models
├── templates/       # Jinja2 HTML (server-rendered pages)
├── static/          # Tailwind input.css / compiled output.css, JS
└── main.py          # app factory, lifespan, logging setup, exception handlers

cronator_lib/        # the logging/artifact/notify library every script imports —
                      # works identically inside Cronator and standalone
alembic/versions/     # migrations, one linear chain (check with `alembic heads`
                      # — more than one means a branch that needs merging)
```

See [Architecture](ARCHITECTURE.md) for how these pieces fit together at
runtime.

## Conventions

- Fix the root cause, not the call site. If a bug is in a function with
  multiple callers, the fix belongs in that function, not in whichever
  caller the bug report happened to mention.
- Don't add abstractions, config knobs, or defensive code for scenarios
  that can't happen given how the code is actually called — three similar
  lines beat a premature helper.
- Comments explain *why*, not *what* — a comment that just restates the
  code it sits above should be deleted, not written.
