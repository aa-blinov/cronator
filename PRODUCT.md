# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

The application is a self-hosted web app. FastAPI serves a JSON API and
server-rendered Jinja2 pages from the same process, with a Tailwind and
daisyUI bundle compiled when the image is built; there is no separate
front-end application. Data lives in PostgreSQL 16 in the Docker stack and in
SQLite for local development. The pages, the API and the scheduler share one
uvicorn process: APScheduler drives the cron jobs in process, and there is no
worker, no broker and no separate queue.

## Users

The README states the situation plainly: a handful of Python scripts that
need to run on a schedule, wanted isolated, observable and resilient, without
setting up a data platform to get there.

The primary user is the person who writes and operates those scripts. Two
roles exist in the code. An `admin` can do everything; a `viewer` can read
scripts, executions, logs, streams, settings and diagnostics, and every
mutating action answers `403`.

`docs/README.md` draws the line: a self-hosted scheduler for one team behind
trusted authentication, not a multi-tenant product.

What the repository does not say: how many people run an instance, and who
they are. There are no download counts, no testimonials and no usage data in
the files, so the size of the audience is unknown, and an audience beyond the
team that owns the deployment is not confirmed.

## Product Purpose

Cronator runs Python scripts on a schedule and keeps the record of what they
did. Each script carries its own virtual environment, with its own Python
version and its own packages, so a schedule is a list of scripts with a time
rather than one shared environment with a conflict waiting to happen.

Success for the user: the script ran when it was supposed to, in an
environment that had the right packages, and a failure reached them before the
next working day. Success for the product: the schedule kept running without
a data platform, a queue or a fleet of workers.

## Positioning

The README places Cronator in the gap between bare `cron` and a full
orchestrator, and says it is not an alternative to Airflow or Prefect.

Against bare `cron`: the schedule lives in a database rather than a crontab,
each script gets its own environment built by the app, the output of every
run is stored and searchable, and a failure becomes a row with a status, an
exit code and an error message.

Against an orchestrator: there is no DAG, no worker, no broker and no plugin
system. One process holds the scheduler, the API and the pages.

What a neighbour could not copy is a constraint rather than a mechanism. The
value of the product comes from the absence of a platform, and a change that
adds a piece of one has to argue against the README's own framing first. No
measured comparison with Airflow or Prefect exists in the repository, and none
should be claimed.

## Operating Context

The workflow, from the code:

1. A script is written in the browser, in an editor built on CodeMirror, or
   dropped into `./scripts` as a file with a `main()` function and a
   `__name__ == "__main__"` guard.
2. It gets a name, a five-field cron expression, a Python version and a list
   of pip packages. The name becomes a directory name, so the schema allows
   letters, digits, `_` and `-` only, and the name cannot begin or end with
   `-` or `_`.
3. On the first run the app builds the virtualenv with
   `uv venv --python <version>`, resolves the packages with `uv pip compile`
   before writing anything to disk, installs `cronator_lib` in editable mode,
   then installs the script's own packages. A manual install streams its log
   to the browser.
4. The scheduler fires the job in UTC. The run becomes a row in `executions`,
   and the output is streamed to the browser while it happens.
5. A failure sends an alert over SMTP or to a webhook URL, and the operator
   can re-run the script, cancel a run, or restore an earlier version of the
   source.

The operator's day: open the app, read the dashboard, see which scripts
failed today and which enabled ones have had no successful run in seven
days, open a failed run to read its output, and act.

The deployment is the Compose stack in `docker-compose.yml`: the app,
PostgreSQL, and a backup service that is a shell loop rather than app code.
Five directories are bind-mounted from the host, `scripts`, `envs`, `logs`,
`data` and `backups`. The people who operate the deployment are on the same
team as the people who write the scripts.

## Capabilities and Constraints

Confirmed by the code:

- 19 built-in script templates, in four categories: monitoring, maintenance,
  data and notification.
- A five-field cron expression per script, evaluated in UTC by an
  in-process APScheduler.
- One `uv` virtualenv per script, with a selectable Python version, resolved
  dependencies and `cronator_lib` installed into it.
- Every run stored with its status, stdout, stderr, exit code, duration,
  trigger and retry attempt.
- Live output over Server-Sent Events, with an in-memory replay buffer that
  lets a reconnecting client catch up.
- Retries: a count from 0 to 10, a delay from 5 to 3600 seconds, and a
  maximum window from 60 to 86400 seconds, all per script.
- Overlap prevention: a run that would overlap a live one is stored as
  `skipped` rather than started.
- Alerts by email over SMTP and by webhook, switchable per script, with the
  failure alert throttled to one per hour.
- Artifacts written by `save_artifact()`, listed and downloadable per run.
- Version snapshots on every save that changes the source, with a revert.
- Field-level audit history of script edits, and a separate audit log of
  user management.
- Bulk enable, disable and delete, with a result per script.
- Two roles, `admin` and `viewer`, enforced on every mutating endpoint and
  on the HTML action routes.
- Login lockout: 10 failed attempts against one username inside 5 minutes
  returns `429`, even for the correct password.
- A CSRF guard on `POST`, `PUT`, `PATCH` and `DELETE` requests whose
  `Origin` header points somewhere else.
- Fernet encryption at rest for the SMTP password and the webhook URL, with
  the key derived from `SECRET_KEY`.
- `/health` with the database, scheduler, disk and migration state, `/metrics`
  in the Prometheus text format, and `/api/diagnostics` with the process,
  database, scheduler and environment snapshot.
- A daily cleanup job at 03:00 UTC that keeps the newest runs per script per
  status: 200 successful, 500 failed, 500 timed out, 100 skipped, 100
  cancelled.
- A daily database backup at 02:00 that writes a gzipped COPY-block dump and
  verifies the archive it just wrote.

Deliberately not true, and worth knowing before a change:

- Scripts are not sandboxed. Each run is a real OS process with the same
  filesystem access as the app itself.
- There is no CPU or memory limit per script. A runaway script can take the
  whole container with it.
- There is no TLS termination in the app. A reverse proxy is expected in
  front of it.
- There is no queue and no second process to scale out to; the deployment
  document has a section on the limits of the single-process design.
- The locale setting stores English or Russian, but the templates are not
  translated yet.
- There is no automatic update, and the backup service and the in-app
  backup are two separate mechanisms.
- The cleanup of executions left running by a crash happens once, at startup,
  and not on a schedule.
- The `db-backup` service dumps at 02:00 on the host clock, not on a
  schedule the app controls.

## Brand Commitments

**Name:** Cronator. The README opens with the line "The home for your
recurring Python automations."

**Voice:** the product reports what happened. A failed run is a row with a
status, an exit code and the captured output. The health endpoint answers
`degraded` and names the component that failed. The documentation separates
what is enforced from what is not, and `docs/SECURITY.md` is explicit about
the gaps on purpose.

**Assets:** the Tailwind and daisyUI bundle, the CodeMirror editor, the
favicon, and the four screenshots in `docs/screenshots/`.

What does not exist: a brand guide, a logo file, a tone document, or a
statement of what the product refuses to become. The name and the README
line are the only written commitments.

## Evidence on Hand

- `README.md` covers the quickstart, the capability list, the reliability
  controls and the environment variables.
- `docs/` holds nine files, of which the index links eight: architecture,
  configuration, deployment, operations, security, the API reference,
  development and the artifacts guide.
- `docs/screenshots/` holds four real screenshots of the interface: the
  dashboard, the execution history, the script editor and the settings page.
- `tests/ui/screenshots/` holds the baseline images the Playwright suite
  compares against.
- `app/script_templates.py` holds the 19 templates as runnable source.
- `app/services/executor.py` is the execution engine, and
  `tests/stateless/services/test_executor.py` covers it.
- `alembic/versions/` holds nine migrations in one chain.
- The suite is 86 test files and 688 test functions counted by name (306
  stateless, 332 stateful, 6 against PostgreSQL, 44 Playwright), before
  pytest's parametrization expands the count at collection time.
- `CHANGELOG.md` has one released version, 0.1.0 dated 2026-09-06, and an
  Unreleased section.

Absent, and not to be invented: no download counts, no usage numbers, no
testimonials, no benchmark against another scheduler, and no comparison of
any kind. Nothing in the repository records who runs an instance.

## Product Principles

1. **One process, no platform.** The pages, the API and the scheduler live in
   one uvicorn process. A change that adds a worker, a queue or a broker has
   to argue against the README's own framing before it argues for itself.
2. **Every run leaves a record.** A run is a row with a status, a timestamp,
   an output and a duration, including the runs that were skipped, cancelled
   or refused for want of disk space. A failure that leaves no row is a bug.
3. **A failure says so.** Failed and timed-out runs are logged at ERROR, a
   script that has failed three times in a row logs a warning, the health
   endpoint names the component that failed, and the dashboard lists the
   scripts that need attention.
4. **The script owns its environment.** The virtualenv belongs to the script,
   with its own Python version and its own packages, and the app builds it
   rather than the operator.
5. **The documentation states what is not enforced.** `docs/SECURITY.md`
   names the missing sandbox and the missing resource limits. Any new copy
   about the product has to agree with it.

## Accessibility & Inclusion

What the code shows:

- The interface is server-rendered HTML on a daisyUI theme, and the theme
  is a setting with a default of `dim`.
- The sidebar buttons carry `aria-label` text for the menu and the close
  control.
- A locale setting exists for English and Russian, stored in the settings
  table and reachable over the API. The templates are not translated yet, so
  the stored preference does not change the words on the page.

What has not been decided: the repository holds no accessibility statement,
no conformance target, and no record of screen-reader testing. The run status
is written out as text beside its colour, but the live log has no live
region for a screen reader to announce, and the status dot animates with no
`prefers-reduced-motion` guard. The Playwright suite compares screenshots,
which catches a layout change and says nothing about semantics. A
keyboard-only path through the script editor is not documented and has not
been tested.
