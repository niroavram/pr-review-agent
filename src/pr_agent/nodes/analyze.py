"""Static analysis node: run every registered analyzer on the PR's changed Python files."""

from __future__ import annotations

import shutil

from langchain_core.runnables import RunnableConfig

from pr_agent.analyzers import ANALYZERS
from pr_agent.deps import get_deps
from pr_agent.gitutil import materialize
from pr_agent.models import ChangedFile, Finding
from pr_agent.state import ReviewState

LINE_SLACK = 1  # tools sometimes report the line before/after the statement


def changed_python_files(files: list[ChangedFile]) -> list[str]:
    """Paths of .py files that still exist in the head commit."""
    return [f.path for f in files if f.path.endswith(".py") and f.status != "deleted"]


def on_added_lines(findings: list[Finding], files: list[ChangedFile]) -> list[Finding]:
    """Keep only findings on lines this PR added (±LINE_SLACK): we review the diff, not history."""
    added = {f.path: set(f.added_lines) for f in files}
    return [
        f
        for f in findings
        if any(f.line + d in added.get(f.file, set()) for d in range(-LINE_SLACK, LINE_SLACK + 1))
    ]


def static_analysis(state: ReviewState, config: RunnableConfig) -> dict:
    """Materialize the head sha, run analyzers, return diff-scoped findings and tool status."""
    deps = get_deps(config)
    ctx = state["ctx"]
    files = changed_python_files(ctx.files)
    workdir = materialize(ctx.repo_path, ctx.head_sha)
    findings: list[Finding] = []
    status: dict[str, str] = {}
    try:
        for name, analyzer in ANALYZERS.items():
            try:
                findings += analyzer(deps.sandbox, workdir, files)
                status[name] = "ok"
            except Exception as e:  # one broken tool must not sink the review
                status[name] = f"error: {e}"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return {"findings": on_added_lines(findings, ctx.files), "tool_status": status}
