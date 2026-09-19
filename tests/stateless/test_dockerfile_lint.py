"""TDD tests for F8: Docker lint in CI.

The Dockerfile and docker-compose files must be linted in CI. We use
`hadolint` (industry standard for Dockerfile linting) and `docker compose
config --quiet` for compose validation.

These tests rely on the host filesystem layout. They auto-skip when run
inside the Docker test container.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _skip_if_not_on_host():
    if not (REPO_ROOT / "Dockerfile").exists():
        pytest.skip("Dockerfile not at expected host path — likely running in container")


def test_dockerfile_exists():
    _skip_if_not_on_host()
    p = REPO_ROOT / "Dockerfile"
    assert p.exists(), f"Dockerfile missing at {p}"


def test_dockerfile_has_user_instruction():
    """Best practice: don't run as root. The Dockerfile must have a USER instruction."""
    _skip_if_not_on_host()
    content = (REPO_ROOT / "Dockerfile").read_text()
    assert "USER " in content, "Dockerfile has no USER instruction (running as root)"


def test_dockerfile_has_healthcheck():
    """Best practice: every service image should declare a HEALTHCHECK."""
    _skip_if_not_on_host()
    content = (REPO_ROOT / "Dockerfile").read_text()
    assert "HEALTHCHECK" in content, "Dockerfile has no HEALTHCHECK instruction"


def test_dockerfile_uses_multi_stage():
    """Best practice: multi-stage builds to keep the runtime image lean."""
    _skip_if_not_on_host()
    content = (REPO_ROOT / "Dockerfile").read_text()
    assert content.count("FROM ") >= 2, "Dockerfile should use multi-stage build"


def test_docker_compose_files_validate():
    """docker compose config --quiet must accept both compose files."""
    _skip_if_not_on_host()
    import subprocess

    for compose_file in ("docker-compose.yml", "docker-compose.test.yml"):
        result = subprocess.run(
            ["docker", "compose", "-f", str(REPO_ROOT / compose_file), "config", "--quiet"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if "Cannot connect to the Docker daemon" in (result.stderr or ""):
            pytest.skip("Docker daemon not available")
        assert result.returncode == 0, f"{compose_file} failed validation:\nstderr: {result.stderr}"


def test_all_services_cap_container_log_growth():
    """Every service in docker-compose.yml needs a bounded `logging` block —
    the default json-file driver has no size cap, and StreamHandler's
    stdout (now including uvicorn access logs too) is unbounded unless
    Docker itself is told to rotate it."""
    _skip_if_not_on_host()
    import yaml

    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text())
    for name, service in compose["services"].items():
        logging_cfg = service.get("logging")
        assert logging_cfg, f"service {name!r} has no logging size cap configured"
        assert logging_cfg.get("options", {}).get("max-size"), (
            f"service {name!r} logging block is missing max-size"
        )


def test_ci_workflow_references_docker_lint():
    """CI workflow should run docker validation as part of docker-validate job."""
    _skip_if_not_on_host()
    p = REPO_ROOT / ".github" / "workflows" / "ci.yml"
    content = p.read_text()
    assert "docker-validate" in content, "no docker-validate job in CI workflow"
    assert "docker compose" in content, "docker-validate job doesn't run docker compose"
