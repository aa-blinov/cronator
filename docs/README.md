# Documentation

The documents for Cronator, a self-hosted scheduler for Python scripts.
The README at the top of the repository is the quick start; this folder
holds everything that is longer than that.

| Document | What it covers |
| --- | --- |
| [architecture.md](architecture.md) | The modules, the request flow, the execution engine, the scheduler and the data model. |
| [CONFIGURATION.md](CONFIGURATION.md) | Every environment variable, which of them are stored in the database, and the order of precedence. |
| [DEPLOYMENT.md](DEPLOYMENT.md) | The Docker Compose stack, the reverse proxy, the log rotation and the upgrades. |
| [OPERATIONS.md](OPERATIONS.md) | Backups and restore, the disk space, the health endpoints and the runbooks. |
| [SECURITY.md](SECURITY.md) | The authentication, the roles, the secrets at rest and the trust model of the scripts. |
| [API.md](API.md) | The REST endpoints, grouped by resource, with a request for each. |
| [DEVELOPMENT.md](DEVELOPMENT.md) | The tests, the migrations, the layout of the project and the conventions of a change. |
| [ARTIFACTS_GUIDE.md](ARTIFACTS_GUIDE.md) | How a script saves a file as an artifact of its run. |
| [screenshots/README.md](screenshots/README.md) | The four pictures of the interface and where each one comes from. |
| [../README.md](../README.md) | The front door: what it does and how to run it. |
| [../AGENTS.md](../AGENTS.md) | The commands, the layout of the tree, and the traps that cost a rebuild to learn. |
| [../PRODUCT.md](../PRODUCT.md) | Who the scheduler is for and what it must not turn into. |
| [../DESIGN.md](../DESIGN.md) | The visual system: the palette, the type and the components of the pages. |

## Reading order

New here: [../README.md](../README.md), then
[architecture.md](architecture.md) for how a run is put together.

Running it on a machine of your own: [DEPLOYMENT.md](DEPLOYMENT.md), then
[CONFIGURATION.md](CONFIGURATION.md) for the values it needs.

Changing the code: [architecture.md](architecture.md), then
[../AGENTS.md](../AGENTS.md) for the traps. The traps cover the paths that
have to reach `update_job()`, the environment a child process receives,
and the rollback that has to stay where it is in the failure path.

Changing the look of the pages: [../DESIGN.md](../DESIGN.md) holds the
tokens, and the bundle itself is built from `app/static/input.css` with
`npm run build:css`.

## What is not here

There is no guide to the scripts themselves. A script is an ordinary
Python file that runs on a schedule, and the library it may import is
described in [ARTIFACTS_GUIDE.md](ARTIFACTS_GUIDE.md).

Some of what is described in these documents is deliberately not built
yet. The sandboxing of a script, and the limits on its memory and its
processor time, are the two that come up most often, and
[SECURITY.md](SECURITY.md) says which is which, so that a deployment can
decide whether it matters.
