"""Git mirror for scripts: git as the human-readable database of scripts.

The database (script_versions with its version_number, script_audit_log
with its field-by-field trail) remains the machine source of truth. This
module mirrors every committed script, with its full content and its
metadata, into a plain git repository — one file per script plus a
metadata json — so the history is readable with `git log`/`git diff`,
reviewable through PRs on a hosted remote, and copyable off the host
entirely.

One-way only: git never writes back into the database. The two never
disagree about content, because nothing reads the mirror except humans
and hosting remotes.

Conflict policy (the remote may be edited directly by a human):
- a remote edit to a file Cronator didn't touch survives the next save
  (Cronator's local commits rebase on top of it);
- a remote edit to the same lines loses on master — the DB wins — but
  parks on an `external/<sha>` side branch first, so nothing anyone
  wrote is ever silently discarded. The reconcile is race-hardened with
  `--force-with-lease` tied to the exact remote sha we saw.

Everything is fail-open: a mirror problem (no git binary, a broken repo,
an unreachable remote) is logged and skipped — mirroring must never
break a script save.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Where the mirror lives. Defaults under ./data — already gitignored and
# mounted in the compose stack; the mirror must never sit inside the app
# repository itself (a mirror repo committed as a gitlink is exactly the
# pollution this placement avoids).
#
# Overridable two ways, in priority order: the Settings UI (UI-editable,
# read by the callers of mirror_script) and the SCRIPT_GIT_REPO_DIR env
# read once at import here — the .env route is a fallback, not the main
# configuration path.
MIRROR_DIR = Path(os.environ.get("SCRIPT_GIT_REPO_DIR", "./data/script_repo")).resolve()


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess | None:
    """Run a git command; None on any failure, logging the reason."""
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("git mirror: %s failed: %s", " ".join(args), e)
        return None


def _ensure_repo(cwd: Path) -> bool:
    """Make sure cwd exists and is a git repository with an identity."""
    if not cwd.exists():
        try:
            cwd.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning("git mirror: cannot create %s: %s", cwd, e)
            return False
    if not (cwd / ".git").exists():
        init = _run_git(["init", "-b", "master"], cwd)
        if init is None or init.returncode != 0:
            # Older git without -b: init and switch the branch explicitly.
            init = _run_git(["init"], cwd)
            if init is None or init.returncode != 0:
                return False
            _run_git(["checkout", "-b", "master"], cwd)
    # A commit needs an identity; fall back to a local one if unset.
    name = _run_git(["config", "user.name"], cwd)
    if name is None or not (name.stdout or "").strip():
        _run_git(["config", "user.name", "Cronator Mirror"], cwd)
        _run_git(["config", "user.email", "cronator-mirror@localhost"], cwd)
    return True


def _is_ancestor(cwd: Path, maybe_ancestor: str, descendant: str) -> bool:
    """True when `maybe_ancestor` is in `descendant`'s history (rc 0)."""
    result = _run_git(["merge-base", "--is-ancestor", maybe_ancestor, descendant], cwd)
    return result is not None and result.returncode == 0


def _resolve_sha(cwd: Path, ref: str) -> str | None:
    """A 40-hex sha for `ref`, or None. A bare rev-parse on some setups
    echoes its argument back on failure, which once named a branch
    `external/origin/mas...` — the shape check refuses anything that is
    not a full sha."""
    result = _run_git(["rev-parse", "--verify", ref], cwd)
    if result is None or result.returncode != 0:
        return None
    sha = (result.stdout or "").strip()
    if len(sha) == 40 and all(c in "0123456789abcdef" for c in sha):
        return sha
    return None


def _abandon_rebase(cwd: Path, local_master_sha: str | None) -> None:
    """Return the mirror to a clean master after a failed reconcile.

    A half-finished rebase (conflict, crash, timeout) must never leak into
    the next save. `--abort` restores the pre-rebase state; if the repo is
    still mid-rebase or detached afterwards, `--quit` drops the in-progress
    state and `checkout -f -B master <captured sha>` puts the authority
    (the pre-rebase local commit) back where mirror commits expect it. The
    captured sha is the local state Cronator already committed — nothing
    committed is ever lost by this reset.
    """
    def _in_rebase() -> bool:
        return (cwd / ".git" / "rebase-merge").exists() or (cwd / ".git" / "rebase-apply").exists()

    if _in_rebase():
        _run_git(["rebase", "--abort"], cwd)
        if _in_rebase():
            _run_git(["rebase", "--quit"], cwd)

    head = _run_git(["symbolic-ref", "-q", "HEAD"], cwd)
    on_master = head is not None and head.returncode == 0 and "master" in (head.stdout or "")
    on_master = on_master and (head.stdout or "").strip() == "refs/heads/master"
    if not on_master and local_master_sha:
        _run_git(["checkout", "-f", "-B", "master", local_master_sha], cwd)
    if local_master_sha:
        _run_git(["reset", "--hard", local_master_sha], cwd)


def _push(cwd: Path, remote_sha: str | None) -> None:
    """Push master to origin; on a non-fast-forward where we hold the
    authority, force-with-lease to the sha we fetched (a commit that
    landed in between — a race — is refused rather than lost). The refspec
    is fully qualified (`master:master`): a bare HEAD is ambiguous while
    the repo is detached and git refuses the whole push."""
    args = ["push", "-u", "origin", "master:master"]
    if remote_sha:
        args = ["push", f"--force-with-lease=master:{remote_sha}", "-u", "origin", "master:master"]
    push = _run_git(args, cwd)
    if push is None or push.returncode != 0:
        err = (push.stderr or "")[-300:] if push is not None else "git unavailable"
        logger.warning("git mirror: push to origin failed (%s); local mirror is intact", err)


def _push_if_remote(cwd: Path, remote: str | None = None) -> None:
    """Reconcile local mirror state with origin and push; fail open."""
    remote = (remote or os.environ.get("SCRIPT_GIT_REMOTE", "")).strip()
    has_origin = _run_git(["remote", "get-url", "origin"], cwd)
    origin_configured = has_origin is not None and has_origin.returncode == 0
    if not remote and not origin_configured:
        return

    local_master_sha = _resolve_sha(cwd, "refs/heads/master")
    if local_master_sha is None:
        logger.warning("git mirror: no local master to push; skipping reconcile")
        return

    if remote:
        if origin_configured:
            _run_git(["remote", "set-url", "origin", remote], cwd)
        else:
            _run_git(["remote", "add", "origin", remote], cwd)

    fetch = _run_git(["fetch", "origin"], cwd)
    if fetch is None or fetch.returncode != 0:
        logger.warning("git mirror: fetch failed; pushing what is already reconciled")
        _push(cwd, None)
        return

    remote_sha = _resolve_sha(cwd, "refs/remotes/origin/master")
    if remote_sha is None:
        # Nothing on the remote yet — the plain push is a fast-forward by definition.
        _push(cwd, None)
        return

    # Everything on the remote is already inside our history: the push
    # fast-forwards and no reconcile is needed.
    if _is_ancestor(cwd, "refs/remotes/origin/master", "refs/heads/master"):
        _push(cwd, remote_sha)
        return

    # Replay Cronator's local commits on top of the remote state; external
    # edits to files Cronator did not touch survive cleanly this way.
    rebase = _run_git(["rebase", "refs/remotes/origin/master"], cwd)
    if rebase is None:
        return
    if rebase.returncode != 0 and not _is_ancestor(
        cwd, "refs/remotes/origin/master", "refs/heads/master"
    ):
        # A real conflict (both sides touched the same lines): park the
        # remote state on a side branch, then restore Cronator's version
        # as the authority. Some setups also report rc != 0 for a rebase
        # that actually applied — the ancestor check tells the difference,
        # so a spurious rc does not discard a healthy state.
        _run_git(["branch", f"external/{remote_sha[:10]}", remote_sha], cwd)
        _abandon_rebase(cwd, local_master_sha)
        logger.warning(
            "git mirror: conflict with remote edits — cronator version wins, "
            "remote state kept on external/%s",
            remote_sha[:10],
        )
        _push(cwd, remote_sha)
        return

    _push(cwd, remote_sha)


def mirror_script(
    script_name: str,
    action: str,
    content: str | None = None,
    metadata: dict | None = None,
    version_number: int | None = None,
    remote: str | None = None,
    repo_dir: Path | None = None,
) -> None:
    """Mirror one script state into the git repo, then push when told to.

    remote / repo_dir come from the caller (Settings via scripts.py) and
    win over the environment; the environment (SCRIPT_GIT_REMOTE /
    SCRIPT_GIT_REPO_DIR) is the fallback, so a fresh install can be
    configured either way and nothing here hardcodes a host layout.
    """
    try:
        mirror_dir = repo_dir or MIRROR_DIR

        if not _ensure_repo(mirror_dir):
            logger.warning("git mirror: repository unavailable, skipping %s", script_name)
            return
        # A reconcile aborted midway must never leak into this save.
        _abandon_rebase(mirror_dir, _resolve_sha(mirror_dir, "refs/heads/master"))

        file_path = mirror_dir / f"{script_name}.py"
        meta_path = mirror_dir / f"{script_name}.meta.json"

        if action == "deleted":
            # Append-only: keep the last state, note the deletion in metadata.
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    meta = {}
                meta["deleted"] = True
                meta["deleted_at_version"] = version_number
                meta_path.write_text(
                    json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
                )
            message = f"script {script_name}: deleted (v{version_number or '?'})"
        else:
            if content is None:
                logger.warning("git mirror: no content for %s, skipping", script_name)
                return
            file_path.write_text(content, encoding="utf-8")
            metadata = dict(metadata or {})
            metadata["mirror_version"] = version_number
            metadata.pop("deleted", None)
            meta_path.write_text(
                json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            message = f"script {script_name}: {action} (v{version_number or '?'})"

        _run_git(["add", "-A"], mirror_dir)
        commit = _run_git(
            ["commit", "-m", message, "--allow-empty", "--no-verify"], mirror_dir
        )
        if commit is None or commit.returncode != 0:
            logger.info("git mirror: nothing to commit for %s", script_name)
            return

        _push_if_remote(mirror_dir, remote=remote)
        logger.info("git mirror: committed %s (%s)", script_name, action)
    except Exception as e:  # pragma: no cover - defensive: never break a save
        logger.warning("git mirror: unexpected error for %s: %s", script_name, e)
