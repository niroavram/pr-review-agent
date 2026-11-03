"""Commit verified patches onto an autofix branch via a temporary worktree (never pushes)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from pr_agent.gitutil import apply_patch, git, rev_parse

_IDENT = ["-c", "user.name=pr-agent", "-c", "user.email=pr-agent@example.invalid"]


def create_branch_with_patches(
    repo_path: str | Path,
    base_commit: str,
    branch: str,
    patches: list[tuple[str, str]],
    message: str,
) -> tuple[list[str], dict[str, str]]:
    """Apply (finding_id, patch) pairs in order on top of base_commit; point `branch` at the
    result. Conflicting patches are dropped. Returns (applied ids, {dropped id: reason})."""
    applied: list[str] = []
    dropped: dict[str, str] = {}
    wt = Path(tempfile.mkdtemp(prefix="pr-agent-wt-"))
    git(repo_path, "worktree", "add", "-q", "--detach", str(wt), base_commit)
    try:
        for fid, patch in patches:
            ok, err = apply_patch(wt, patch if patch.endswith("\n") else patch + "\n")
            if ok:
                applied.append(fid)
            else:
                dropped[fid] = err.strip() or "patch did not apply"
        if applied:
            git(wt, "add", "-A")
            git(wt, *_IDENT, "commit", "-q", "-m", message)
            git(repo_path, "branch", "-f", branch, rev_parse(wt, "HEAD"))
    finally:
        git(repo_path, "worktree", "remove", "--force", str(wt), check=False)
    return applied, dropped
