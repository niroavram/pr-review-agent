"""Thin, read-mostly git helpers. All writes go through temporary worktrees."""

from __future__ import annotations

import subprocess
import tarfile
import tempfile
from io import BytesIO
from pathlib import Path


class GitError(RuntimeError):
    pass


def git(repo: str | Path, *args: str, check: bool = True) -> str:
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check and p.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {p.stderr.strip()}")
    return p.stdout


def rev_parse(repo: str | Path, ref: str) -> str:
    return git(repo, "rev-parse", ref).strip()


def show_file(repo: str | Path, sha: str, path: str) -> str | None:
    """File content at a commit, or None if absent. Used to read config from the BASE sha."""
    p = subprocess.run(
        ["git", "-C", str(repo), "show", f"{sha}:{path}"], capture_output=True, text=True
    )
    return p.stdout if p.returncode == 0 else None


def materialize(repo: str | Path, sha: str, dest: Path | None = None) -> Path:
    """Export a commit's tree into a fresh directory (no .git). Returns the directory."""
    dest = dest or Path(tempfile.mkdtemp(prefix="pr-agent-"))
    data = subprocess.run(
        ["git", "-C", str(repo), "archive", "--format=tar", sha], capture_output=True, check=True
    ).stdout
    with tarfile.open(fileobj=BytesIO(data)) as tar:
        tar.extractall(dest, filter="data")
    return dest


def apply_patch(workdir: Path, patch: str, check_only: bool = False) -> tuple[bool, str]:
    """`git apply` a unified diff inside a (non-git) directory."""
    args = ["git", "apply", "--whitespace=nowarn"] + (["--check"] if check_only else []) + ["-"]
    p = subprocess.run(args, cwd=workdir, input=patch, capture_output=True, text=True)
    return p.returncode == 0, p.stderr
