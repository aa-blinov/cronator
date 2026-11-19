"""The script git-mirror (app/services/script_git.py) as the readable
database of scripts: one file + one metadata json per script, one commit
per state change, append-only on deletion.

The conflict/reconcile tests stand up a local bare remote — the same
contract GitHub serves — and assert the documented policy:
- an external edit to a file Cronator didn't touch survives rebase;
- an external edit to the same file loses on master (the DB wins) but
  parks on a external/<sha> side branch, so nothing is silently lost.
"""

import json
import subprocess
from pathlib import Path

import pytest

from app.services import script_git

# The fixture patches _push_if_remote with a no-op for the pure-local
# tests; the reconcile tests below re-enable the real one.
_REAL_PUSH_IF_REMOTE = script_git._push_if_remote


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"git {args} in {cwd}: {r.stderr}"
    return r


@pytest.fixture
def mirror_dir(tmp_path, monkeypatch):
    """Point the mirror at a fresh tmp dir (repo env read at import time)."""
    target = tmp_path / "script_repo"
    target.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(script_git, "MIRROR_DIR", target)
    monkeypatch.setattr(script_git, "_push_if_remote", lambda cwd: None)
    return target


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


def test_revert_recreates_the_old_state_as_a_new_commit(mirror_dir):
    """The revert path: mirroring the old version as a new "updated" keeps
    the whole history (v1 -> v2 -> back to v1 is three commits) and the
    working tree ends on the reverted content — the mirror never loses
    the v2 detour, which is exactly what git buys here.
    """
    script_git.mirror_script("probe", "created", content='v1\n', version_number=1)
    script_git.mirror_script("probe", "updated", content='v2\n', version_number=2)
    script_git.mirror_script("probe", "updated", content='v1\n', version_number=3)
    assert (mirror_dir / 'probe.py').read_text(encoding='utf-8') == 'v1\n'
    commits = _commits(mirror_dir)
    assert len(commits) == 3
    assert "script probe: updated (v3)" in commits[0]
    meta = json.loads((mirror_dir / "probe.meta.json").read_text(encoding="utf-8"))
    assert meta["mirror_version"] == 3


def test_settings_override_the_env(mirror_dir, tmp_path, monkeypatch):
    """remote / repo_dir passed to mirror_script win over the module
    defaults — that is the settings-driven path (UI over .env).
    """
    alt_repo = tmp_path / "alt_repo"
    alt_repo.mkdir()
    script_git.mirror_script(
        "probe",
        "created",
        content='print(alt)\n',
        version_number=1,
        repo_dir=alt_repo,
        remote="https://example.invalid/nope.git",
    )
    assert (alt_repo / 'probe.py').read_text(encoding='utf-8') == 'print(alt)\n'
    assert _commits(alt_repo), "commit must land in the overridden repo"
    assert not (mirror_dir / "probe.py").exists(), "default mirror must stay untouched"
    # example.invalid does not resolve; the push must fail open, not raise.
    # No assertion beyond "mirror_script returned".


def test_deleted_script_keeps_history(mirror_dir):
    """Append-only: a deletion keeps the file and marks the metadata."""
    script_git.mirror_script("probe", "created", content="gone soon\n", version_number=1)
    script_git.mirror_script("probe", "deleted", version_number=1)
    assert (mirror_dir / "probe.py").exists(), "deletion must not erase the last state"
    meta = json.loads((mirror_dir / "probe.meta.json").read_text(encoding="utf-8"))
    assert meta["deleted"] is True
    assert any("deleted" in c for c in _commits(mirror_dir))


def test_mirror_never_raises_on_broken_repo(mirror_dir, monkeypatch):
    """Fail-open by contract: a mirror problem is logged, a save proceeds."""

    def broken_run(*args, **kwargs):
        raise OSError("git binary disappeared")

    monkeypatch.setattr(script_git, "_run_git", broken_run)
    script_git.mirror_script("probe", "created", content="x\n", version_number=1)


# --- Reconcile with a remote that got edited directly (the conflict case) ---


def _bare_remote(tmp_path: Path) -> Path:
    """A local bare repo plays the remote host of a private git mirror."""
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "master", str(remote)],
        capture_output=True,
        timeout=30,
    )
    return remote


def _enable_real_push(mirror_dir: Path, remote: Path, monkeypatch) -> None:
    """Init the mirror repo as a clone context with origin=remote and
    re-enable the real push (the fixture patches it with a no-op)."""
    _git(mirror_dir, "init", "-b", "master")
    _git(mirror_dir, "config", "user.email", "t@t")
    _git(mirror_dir, "config", "user.name", "t")
    _git(mirror_dir, "remote", "add", "origin", str(remote))
    monkeypatch.setattr(script_git, "_push_if_remote", _REAL_PUSH_IF_REMOTE)


def _external_clone(remote: Path, where: Path, edit: dict[str, str]) -> None:
    """Act as a second person who edited the bare remote directly."""
    _git(remote.parent, "clone", "--quiet", str(remote), str(where))
    _git(where, "config", "user.email", "ext@t")
    _git(where, "config", "user.name", "ext")
    for name, content in edit.items():
        (where / name).write_text(content, encoding="utf-8")
    _git(where, "add", "-A")
    _git(where, "commit", "-m", "external edit")
    _git(where, "push", "--quiet", "origin", "master")


def test_first_push_lands_on_the_remote(mirror_dir, tmp_path, monkeypatch):
    remote = _bare_remote(tmp_path)
    _enable_real_push(mirror_dir, remote, monkeypatch)

    script_git.mirror_script("probe", "created", content="v1\n", version_number=1)

    # a bare remote has no worktree — read it through the mirror's remote-tracking ref
    head = _git(mirror_dir, "ls-remote", "origin", "master").stdout.split()
    assert head, "the create must have been pushed"


def test_external_edit_touching_other_file_survives_rebase(mirror_dir, tmp_path, monkeypatch):
    """Layer 1 of the conflict policy."""
    remote = _bare_remote(tmp_path)
    _enable_real_push(mirror_dir, remote, monkeypatch)

    script_git.mirror_script("probe", "created", content="v1\n", version_number=1)

    other = tmp_path / "external_clone"
    _external_clone(remote, other, {"NOTES.md": "a human note\n"})

    script_git.mirror_script("probe", "updated", content="v2\n", version_number=2)

    _git(mirror_dir, "fetch", "origin")
    remote_tree = _git(mirror_dir, "ls-tree", "origin/master").stdout
    assert "probe.py" in remote_tree
    assert "NOTES.md" in remote_tree, "external edit to another file must survive"
    assert _git(mirror_dir, "show", "origin/master:probe.py").stdout == "v2\n"


def test_conflicting_external_edit_goes_to_a_side_branch(mirror_dir, tmp_path, monkeypatch):
    """Layer 2 of the conflict policy: the DB wins on master; the external
    version parks on external/<sha> so nothing is silently lost."""
    remote = _bare_remote(tmp_path)
    _enable_real_push(mirror_dir, remote, monkeypatch)

    script_git.mirror_script("probe", "created", content="v1\n", version_number=1)

    other = tmp_path / "external_clone2"
    _external_clone(remote, other, {"probe.py": "hacked by hand\n"})
    remote_sha = _git(mirror_dir, "ls-remote", "origin", "master").stdout.split()[0]

    script_git.mirror_script("probe", "updated", content="v2\n", version_number=2)

    _git(mirror_dir, "fetch", "origin")
    master = _git(mirror_dir, "show", "origin/master:probe.py").stdout
    assert master == "v2\n", "cronator (the DB) must win on master"
    side = _git(mirror_dir, "show", f"external/{remote_sha[:10]}:probe.py").stdout
    assert side == "hacked by hand\n", "the external version must survive on the side branch"
