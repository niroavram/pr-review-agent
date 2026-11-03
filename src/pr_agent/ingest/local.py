"""Build a PRContext from two refs in a local git repo (`--local` mode)."""

from __future__ import annotations

import re
from pathlib import Path

from pr_agent.gitutil import git, rev_parse
from pr_agent.ingest.diff import parse_diff
from pr_agent.models import PRContext


def _branch_name(repo: Path, head: str) -> str | None:
    """The branch name `head` refers to, or None if it is not a branch."""
    if head == "HEAD":
        return git(repo, "symbolic-ref", "--short", "-q", "HEAD", check=False).strip() or None
    found = git(repo, "rev-parse", "--verify", "-q", f"refs/heads/{head}", check=False)
    return head if found.strip() else None


def _sanitize(name: str) -> str:
    """Make a branch name safe as one branch/dir component: `case/01-x` -> `case-01-x`."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")


def load_local(repo_path: str | Path, base: str = "main", head: str = "HEAD") -> PRContext:
    """PR semantics: the diff runs from merge-base(base, head) to head."""
    repo = Path(repo_path).resolve()
    head_sha = rev_parse(repo, head)
    base_sha = git(repo, "merge-base", base, head_sha).strip()
    diff = git(repo, "diff", base_sha, head_sha)
    title, _, rest = git(repo, "log", "-1", "--format=%B", head_sha).strip().partition("\n")
    branch = _branch_name(repo, head)
    return PRContext(
        repo_path=str(repo),
        repo_name=repo.name,
        pr_id=_sanitize(branch) if branch else head_sha[:8],
        base_sha=base_sha,
        head_sha=head_sha,
        head_ref=head,
        title=title.strip(),
        description=rest.strip(),
        files=parse_diff(diff),
        diff=diff,
        mode="local",
    )
