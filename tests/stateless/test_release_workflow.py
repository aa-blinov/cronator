"""TDD tests for F22: GitHub release workflow.

When a tag matching v*.*.* is pushed, CI must:
1. Run the existing test suite as a sanity check
2. Build the Docker image
3. Create a GitHub release with the CHANGELOG excerpt for that version
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_release_workflow_file_exists():
    p = REPO_ROOT / ".github" / "workflows" / "release.yml"
    assert p.exists(), f"Release workflow missing at {p}"


def test_release_workflow_triggers_on_semver_tag():
    """Release workflow must trigger on tags matching v*.*. ."""
    content = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text()
    assert "tags:" in content
    assert "v*.*.*" in content, "release workflow should trigger on v*.*.* tags"


def test_release_workflow_runs_tests():
    """Sanity: the release workflow runs tests before publishing."""
    content = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text()
    assert "pytest" in content or "ruff" in content, (
        "release workflow must run lint or tests before publishing"
    )


def test_release_workflow_builds_docker_image():
    content = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text()
    assert "docker build" in content or "docker buildx build" in content


def test_release_workflow_uses_changelog():
    """The release notes must come from CHANGELOG.md, not from auto-generation only."""
    content = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text()
    assert "CHANGELOG" in content, "release notes should be sourced from CHANGELOG.md"


def test_release_workflow_has_contents_write_permission():
    """Creating a release requires `contents: write` permission."""
    content = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text()
    assert "contents: write" in content, "release workflow needs contents: write permission"
