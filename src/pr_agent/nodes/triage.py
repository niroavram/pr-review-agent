"""Deterministic triage: decide which reviewers run and which files are out of scope."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from langchain_core.runnables import RunnableConfig

from pr_agent.ingest.diff import is_reviewable
from pr_agent.models import ChangedFile
from pr_agent.state import ReviewState

MAX_DIFF_LINES = 3000
ALL_REVIEWERS = ["security", "bug", "conventions"]

DOC_SUFFIXES = {".md", ".rst", ".txt", ".adoc"}
CONFIG_SUFFIXES = {".toml", ".yaml", ".yml", ".json", ".ini", ".cfg", ".conf", ".env"}
CONFIG_NAMES = {"Dockerfile", "Makefile", ".gitignore", ".gitattributes", ".editorconfig"}


def is_doc(path: str) -> bool:
    """Prose files and anything under a top-level `docs/` directory."""
    p = PurePosixPath(path)
    return p.suffix.lower() in DOC_SUFFIXES or p.parts[0] == "docs"


def is_config(path: str) -> bool:
    """Configuration and build files."""
    p = PurePosixPath(path)
    return p.suffix.lower() in CONFIG_SUFFIXES or p.name in CONFIG_NAMES


def _no_python_note(files: list[ChangedFile]) -> str:
    """Why the LLM reviewers were skipped for a PR without reviewable Python."""
    paths = [f.path for f in files]
    if paths and all(is_doc(p) for p in paths):
        return "Docs-only PR: LLM reviewers skipped."
    if paths and all(is_config(p) for p in paths):
        return "Config-only PR: LLM reviewers skipped."
    if paths and all(is_doc(p) or is_config(p) for p in paths):
        return "Docs/config-only PR: LLM reviewers skipped."
    return "No Python changes: LLM reviewers skipped."


def triage(state: ReviewState, config: RunnableConfig) -> dict[str, Any]:
    """Pick reviewers from the changed files and diff size. No LLM calls.

    - skipped_files: lock/binary/minified/vendored/generated files (`is_reviewable` is False).
    - python_files: reviewable, non-deleted `.py` files.
    - No python_files (e.g. docs-only or config-only PRs) -> no LLM reviewers.
    - A huge diff -> only the security reviewer.
    """
    ctx = state["ctx"]
    skipped = [f.path for f in ctx.files if not is_reviewable(f.path)]
    py = [
        f.path
        for f in ctx.files
        if f.path.endswith(".py") and f.status != "deleted" and is_reviewable(f.path)
    ]
    notes: list[str] = []
    reviewers = list(ALL_REVIEWERS) if py else []
    if not py:
        notes.append(_no_python_note(ctx.files))
    elif ctx.diff.count("\n") > MAX_DIFF_LINES:
        reviewers = ["security"]
        notes.append(f"Diff over {MAX_DIFF_LINES} lines: only the security reviewer ran.")
    if skipped:
        notes.append(f"Skipped {len(skipped)} non-reviewable file(s) (lock, binary, generated).")
    return {
        "triage": {
            "reviewers": reviewers,
            "python_files": py,
            "skipped_files": skipped,
            "notes": notes,
        }
    }
