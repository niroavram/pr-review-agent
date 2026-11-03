"""Deterministic triage: decide which reviewers run and which files are out of scope."""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from pr_agent.state import ReviewState

MAX_DIFF_LINES = 3000
ALL_REVIEWERS = ["security", "bug", "conventions"]


def triage(state: ReviewState, config: RunnableConfig) -> dict:
    ctx = state["ctx"]
    py = [f.path for f in ctx.files if f.path.endswith(".py") and f.status != "deleted"]
    skipped = [f.path for f in ctx.files if not f.path.endswith(".py")]
    notes: list[str] = []
    reviewers = ALL_REVIEWERS if py else []
    if not py:
        notes.append("No Python changes: LLM reviewers skipped.")
    if ctx.diff.count("\n") > MAX_DIFF_LINES:
        reviewers = ["security"]
        notes.append(f"Diff over {MAX_DIFF_LINES} lines: only the security reviewer ran.")
    return {
        "triage": {
            "reviewers": reviewers,
            "python_files": py,
            "skipped_files": skipped,
            "notes": notes,
        }
    }
