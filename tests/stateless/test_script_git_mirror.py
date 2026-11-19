"""The script git-mirror (app/services/script_git.py) as the readable
database of scripts: one file + one metadata json per script, one commit
per state change, append-only on deletion."""

import json
import subprocess
from pathlib import Path

import pytest

from app.services import script_git


def _commits(repo: Path) -> list[str]:
    log = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert log.returncode == 0, log.stderr
    return [line for line in log.stdout.splitlines() if line.strip()]


@pytest.fixture
def mirror_dir(tmp_path, monkeypatch):
    """Point the mirror at a fresh tmp dir (repo env read at import time)."""
    target = tmp_path / "script_repo"
    monkeypatch.setattr(script_git, "MIRROR_DIR", target)
    monkeypatch.setattr(script_git, "_push_if_remote", lambda cwd: None)
    return target


def test_created_script_is_a_commit(mirror_dir):
    script_git.mirror_script(
        "probe",
        "created",
        content="print('hi')\n",
        version_number=1,
        metadata={"description": "probe script"},
    )
    assert (mirror_dir / "probe.py").read_text(encoding="utf-8") == "print('hi')\n"
    meta = json.loads((mirror_dir / "probe.meta.json").read_text(encoding="utf-8"))
    assert meta["mirror_version"] == 1
    assert meta["description"] == "probe script"
    commits = _commits(mirror_dir)
    assert len(commits) == 1
    assert "script probe: created (v1)" in commits[0]


def test_updated_script_grows_history(mirror_dir):
    script_git.mirror_script("probe", "created", content="v1\n", version_number=1)
    script_git.mirror_script("probe", "updated", content="v2\n", version_number=2)
    assert (mirror_dir / "probe.py").read_text(encoding="utf-8") == "v2\n"
    assert len(_commits(mirror_dir)) == 2
    meta = json.loads((mirror_dir / "probe.meta.json").read_text(encoding="utf-8"))
    assert meta["mirror_version"] == 2


def test_deleted_script_keeps_history(mirror_dir):
    """Append-only: a deletion keeps the file and marks the metadata."""
    script_git.mirror_script("probe", "created", content="gone soon\n", version_number=1)
    script_git.mirror_script("probe", "deleted", version_number=1)
    assert (mirror_dir / "probe.py").exists(), "deletion must not erase the last state"
    meta = json.loads((mirror_dir / "probe.meta.json").read_text(encoding="utf-8"))
    assert meta["deleted"] is True
    commits = _commits(mirror_dir)
    assert any("deleted" in c for c in commits)


def test_mirror_never_raises_on_broken_repo(mirror_dir, monkeypatch):
    """Fail-open by contract: a mirror problem is logged, a save proceeds."""

    def broken_run(*args, **kwargs):
        raise OSError("git binary disappeared")

    monkeypatch.setattr(script_git, "_run_git", broken_run)
    # must not raise
    script_git.mirror_script("probe", "created", content="x\n", version_number=1)


def test_unsafe_repo_state_skips_cleanly(mirror_dir, monkeypatch):
    """A git command returning a failure must skip, not raise or half-write."""
    call = {"n": 0}

    def failing_init(*args, **kwargs):
        call["n"] += 1
        if call["n"] == 1:
            return None  # init fails
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(script_git, "_run_git", failing_init)
    script_git.mirror_script("probe", "created", content="x\n", version_number=1)
    assert call["n"] == 1, "must stop at the first failed step"
    assert not list(mirror_dir.glob("probe*")) or (
        mirror_dir / "probe.py"
    ).exists() is False
