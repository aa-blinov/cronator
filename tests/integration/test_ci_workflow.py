"""TDD tests for F5: CI workflow + Ruff enforcement.

The CI workflow must:
1. Exist at .github/workflows/ci.yml
2. Run ruff lint on every push/PR
3. Run docker compose validation
4. Run the project's test suite
"""

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_ci_workflow_file_exists():
    """CI workflow must be present."""
    p = REPO_ROOT / ".github" / "workflows" / "ci.yml"
    assert p.exists(), f"CI workflow missing at {p}"


def test_ci_workflow_runs_ruff():
    """CI workflow must invoke ruff (or astral-sh/ruff-action)."""
    p = REPO_ROOT / ".github" / "workflows" / "ci.yml"
    content = p.read_text()
    assert "ruff" in content.lower(), f"CI workflow does not reference ruff:\n{content}"


def test_ci_workflow_validates_docker_compose():
    """CI workflow must validate docker-compose configuration."""
    p = REPO_ROOT / ".github" / "workflows" / "ci.yml"
    content = p.read_text()
    assert "docker compose" in content or "docker-compose" in content, (
        f"CI workflow does not validate compose:\n{content}"
    )


def test_ci_workflow_runs_tests():
    """CI workflow must run the test suite."""
    p = REPO_ROOT / ".github" / "workflows" / "ci.yml"
    content = p.read_text()
    assert "pytest" in content or "docker-compose.test" in content, (
        f"CI workflow does not run tests:\n{content}"
    )


def test_ruff_passes_locally():
    """Actual ruff run on app/cronator_lib must be clean."""
    try:
        result = subprocess.run(
            ["ruff", "check", "app/", "cronator_lib/"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            timeout=60,
        )
    except FileNotFoundError:
        pytest.skip("ruff is not installed in this environment")
    if result.returncode != 0:
        pytest.fail(
            f"ruff check failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
