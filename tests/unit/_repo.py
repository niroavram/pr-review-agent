"""Tiny two-commit git repos for analyzer / test-runner tests."""

from __future__ import annotations

from pathlib import Path

from pr_agent.gitutil import git, rev_parse
from pr_agent.models import ChangedFile, PRContext

_IDENT = ["-c", "user.name=t", "-c", "user.email=t@example.invalid"]


def _write(repo: Path, files: dict[str, str | None]) -> None:
    for rel, content in files.items():
        path = repo / rel
        if content is None:
            path.unlink(missing_ok=True)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def make_pr(
    repo: Path, base: dict[str, str | None], head: dict[str, str | None], mode: str = "local"
) -> PRContext:
    """Commit `base`, then overlay `head` (None deletes) on top. Every head file is 'changed'
    with all of its lines added."""
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q", "-b", "main")
    _write(repo, base)
    git(repo, "add", "-A")
    git(repo, *_IDENT, "commit", "-q", "-m", "base")
    base_sha = rev_parse(repo, "HEAD")
    _write(repo, head)
    git(repo, "add", "-A")
    git(repo, *_IDENT, "commit", "-q", "--allow-empty", "-m", "head")
    files = [
        ChangedFile(
            path=rel,
            status="deleted" if content is None else "modified",
            added_lines=list(range(1, len((content or "").splitlines()) + 1)),
        )
        for rel, content in head.items()
    ]
    return PRContext(
        repo_path=str(repo),
        repo_name="t",
        pr_id="t",
        base_sha=base_sha,
        head_sha=rev_parse(repo, "HEAD"),
        files=files,
        mode=mode,  # type: ignore[arg-type]
    )
