"""Git mirror for scripts: git as the human-readable database of scripts.

The database (script_versions with its version_number, script_audit_log
with its field-by-field trail) remains the machine source of truth. This
module mirrors every committed script, with its full content and its
metadata, into a plain git repository — one file per script plus a
metadata json — so that the history is readable with `git log`/`git diff`,
reviewable through PRs on a hosted remote, and copyable off the host
entirely.

One-way only: git never writes back into the database. The two never
disagree about content, because nothing reads the mirror except humans
and hosting remotes.

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

# Where the mirror lives. One directory, one git repo, one file per script
# with the script's content plus a metadata json alongside.
repo_root_env = "SCRIPT_GIT_REPO_DIR"
MIRROR_DIR = Path(os.environ.get(repo_root_env, "./script_repo")).resolve()


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
        init = _run_git(["init"], cwd)
        if init is None or init.returncode != 0:
            return False
    # A commit needs an identity; fall back to a local one if unset.
    name = _run_git(["config", "user.name"], cwd)
    if name is None or not (name.stdout or "").strip():
        _run_git(["config", "user.name", "Cronator Mirror"], cwd)
        _run_git(["config", "user.email", "cronator-mirror@localhost"], cwd)
    return True


def _push_if_remote(cwd: Path) -> None:  # pragma: no cover - network path
    """Push to origin when SCRIPT_GIT_REMOTE is set; fail open."""
    remote = os.environ.get("SCRIPT_GIT_REMOTE", "").strip()
    remote_url_set = _run_git(["remote", "get-url", "origin"], cwd)
    if not remote and (remote_url_set is None or remote_url_set.returncode != 0):
        return
    if remote and remote_url_set is not None and remote_url_set.returncode == 0:
        _run_git(["remote", "set-url", "origin", remote], cwd)
    elif remote:
        add = _run_git(["remote", "add", "origin", remote], cwd)
        if add is None or add.returncode != 0:
            return
    push = _run_git(["push", "-u", "origin", "HEAD"], cwd)
    if push is None or push.returncode != 0:
        push = _run_git(["push"], cwd)
        if push is None or push.returncode != 0:
            logger.warning("git mirror: push to origin failed; local mirror is up to date")


def mirror_script(
    script_name: str,
    action: str,
    content: str | None = None,
    metadata: dict | None = None,
    version_number: int | None = None,
) -> None:
    """Mirror one script state into the git repo, then push when told to.

    action: "created" | "updated" | "deleted".
    Deletion keeps the history (the file's last state is committed with a
    note instead of being erased) — the mirror is append-only by policy.
    """
    try:
        if not _ensure_repo(MIRROR_DIR):
            logger.warning("git mirror: repository unavailable, skipping %s", script_name)
            return

        file_path = MIRROR_DIR / f"{script_name}.py"
        meta_path = MIRROR_DIR / f"{script_name}.meta.json"

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
            # Whatever the last state was, it stays on disk — history only grows.
        else:
            if content is None:
                logger.warning("git mirror: no content for %s, skipping", script_name)
                return
            file_path.write_text(content, encoding="utf-8")
            metadata = dict(metadata or {})
            metadata["mirror_version"] = version_number
            meta_path.write_text(
                json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            message = f"script {script_name}: {action} (v{version_number or '?'})"

        add = _run_git(["add", "-A"], cwd=MIRROR_DIR)
        if add is None or add.returncode != 0:
            logger.warning("git mirror: git add failed for %s", script_name)
            return
        commit = _run_git(["commit", "-m", message, "--allow-empty"], cwd=MIRROR_DIR)
        if commit is None or commit.returncode != 0:
            # Nothing new to commit is not a failure for a mirror.
            logger.info("git mirror: nothing to commit for %s", script_name)
            return

        _push_if_remote(MIRROR_DIR)
        logger.info("git mirror: committed %s (%s)", script_name, action)
    except Exception as e:  # pragma: no cover - defensive: never break a save
        logger.warning("git mirror: unexpected error for %s: %s", script_name, e)
