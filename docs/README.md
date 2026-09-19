# Cronator Documentation

This directory holds the documentation that doesn't fit in the top-level
[README](../README.md) (which is the quickstart / marketing page). Start there
if you just want to run Cronator; come here when you need to operate, secure,
or extend it.

| Document                              | What's in it                                                                              |
| -------------------------------------- | ------------------------------------------------------------------------------------------- |
| [Architecture](ARCHITECTURE.md)        | Components, request flow, the execution engine, data model, background jobs                |
| [Configuration](CONFIGURATION.md)      | Every environment variable, what's env-only vs. DB-backed, precedence rules                |
| [Deployment](DEPLOYMENT.md)            | Docker Compose production setup, reverse proxy, log rotation, resource sizing, upgrades     |
| [Operations](OPERATIONS.md)            | Backups & restore, disk space, alerting behavior, health/diagnostics endpoints, runbooks    |
| [Security](SECURITY.md)                | Auth model, RBAC scope (and its limits), secrets at rest, script trust model               |
| [API Reference](API.md)                | REST endpoints grouped by resource, with curl examples                                      |
| [Development](DEVELOPMENT.md)          | Running tests, migrations workflow, project layout, contribution conventions               |
| [Artifacts Guide](ARTIFACTS_GUIDE.md)  | How scripts save files as execution artifacts, from `cronator_lib.save_artifact`            |

## Who this is for

Cronator is a self-hosted scheduler for a small set of Python scripts run by
one team behind trusted authentication — not a multi-tenant SaaS product.
Some of what's documented here is scope that's deliberately *not* built yet
(full per-endpoint RBAC, script sandboxing); [Security](SECURITY.md) is
explicit about which is which so you can decide whether it matters for your
deployment.
