"""Static analysis node: run every registered analyzer on the PR's changed files."""

from __future__ import annotations

import shutil

from langchain_core.runnables import RunnableConfig

from pr_agent.analyzers import AnalysisContext, run_all
from pr_agent.deps import get_deps
from pr_agent.gitutil import materialize
from pr_agent.models import ChangedFile, Finding
from pr_agent.state import ReviewState

LINE_SLACK = 1  # tools sometimes report the line before/after the statement


def changed_python_files(files: list[ChangedFile]) -> list[str]:
    """Paths of .py files that still exist in the head commit."""
    return [f.path for f in files if f.path.endswith(".py") and f.status != "deleted"]


def head_files(files: list[ChangedFile]) -> list[str]:
    """Paths of all changed files that still exist in the head commit (analyzers filter)."""
    return [f.path for f in files if f.status != "deleted"]


def on_added_lines(findings: list[Finding], files: list[ChangedFile]) -> list[Finding]:
    """Keep only findings on lines this PR added (±LINE_SLACK): we review the diff, not history."""
    added = {f.path: set(f.added_lines) for f in files}
    return [
        f
        for f in findings
        if any(f.line + d in added.get(f.file, set()) for d in range(-LINE_SLACK, LINE_SLACK + 1))
    ]


def static_analysis(state: ReviewState, config: RunnableConfig) -> dict:
    """Materialize head (code under review) and base (trusted configs), run all analyzers,
    return diff-scoped findings and per-tool status."""
    deps = get_deps(config)
    ctx = state["ctx"]
    workdir = materialize(ctx.repo_path, ctx.head_sha)
    base_dir = materialize(ctx.repo_path, ctx.base_sha)
    try:
        files = [f for f in head_files(ctx.files) if (workdir / f).is_file()]
        actx = AnalysisContext(workdir, base_dir, files, deps.sandbox)
        findings, status = run_all(actx)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        shutil.rmtree(base_dir, ignore_errors=True)
    return {"findings": on_added_lines(findings, ctx.files), "tool_status": status}
