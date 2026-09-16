"""TDD tests for F8: Docker lint in CI.

The Dockerfile and docker-compose files must be linted in CI. We use
`hadolint` (industry standard for Dockerfile linting) and `docker compose
config --quiet` for compose validation.

hadolint is opt-in: many real-world Dockerfiles trigger warnings we don't
want to fail CI on. We use it as informational and only fail on ERRORs.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_dockerfile_exists():
    p = REPO_ROOT / "Dockerfile"
    assert p.exists(), f"Dockerfile missing at {p}"


def test_dockerfile_has_user_instruction():
    """Best practice: don't run as root. The Dockerfile must have a USER instruction."""
    content = (REPO_ROOT / "Dockerfile").read_text()
    assert "USER " in content, "Dockerfile has no USER instruction (running as root)"


def test_dockerfile_has_healthcheck():
    """Best practice: every service image should declare a HEALTHCHECK."""
    content = (REPO_ROOT / "Dockerfile").read_text()
    assert "HEALTHCHECK" in content, "Dockerfile has no HEALTHCHECK instruction"


def test_dockerfile_uses_multi_stage():
    """Best practice: multi-stage builds to keep the runtime image lean."""
    content = (REPO_ROOT / "Dockerfile").read_text()
    assert content.count("FROM ") >= 2, "Dockerfile should use multi-stage build"


def test_docker_compose_files_validate():
    """docker compose config --quiet must accept both compose files."""
    import subprocess

    for compose_file in ("docker-compose.yml", "docker-compose.test.yml"):
        result = subprocess.run(
            ["docker", "compose", "-f", str(REPO_ROOT / compose_file), "config", "--quiet"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # If docker isn't available, skip
        if "Cannot connect to the Docker daemon" in (result.stderr or ""):
            pytest.skip("Docker daemon not available")
        assert result.returncode == 0, (
            f"{compose_file} failed validation:\nstderr: {result.stderr}"
        )


def test_ci_workflow_references_docker_lint():
    """CI workflow should run docker validation as part of docker-validate job."""
    p = REPO_ROOT / ".github" / "workflows" / "ci.yml"
    content = p.read_text()
    assert "docker-validate" in content, "no docker-validate job in CI workflow"
    assert "docker compose" in content, "docker-validate job doesn't run docker compose"
