"""apply_fixes: land this round's shippable fixes on autofix/<pr> and record the round."""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from pr_agent.gitutil import rev_parse
from pr_agent.models import FixProposal, Level
from pr_agent.publish.git_branch import create_branch_with_patches
from pr_agent.state import ReviewState


def shippable(state: ReviewState) -> list[FixProposal]:
    """AUTO fixes, or approved SUGGEST fixes, whose verification passed."""
    levels = {d.finding_id: d.level for d in state.get("decisions", [])}
    passed = {v.finding_id for v in state.get("verifications", []) if v.passed}
    approved = set(state.get("approved") or [])

    def ships(fid: str) -> bool:
        level = levels.get(fid)
        return level is Level.AUTO or (level is Level.SUGGEST and fid in approved)

    return [
        f
        for f in state.get("fixes", [])
        if f.patch and f.finding_id in passed and ships(f.finding_id)
    ]


def autofix_branch(state: ReviewState) -> str:
    return f"autofix/{state['ctx'].pr_id}"


def apply_fixes(state: ReviewState, config: RunnableConfig) -> dict[str, Any]:
    """Commit on top of the current head (the PR head in round 1, the autofix tip later)."""
    ctx = state["ctx"]
    ship = shippable(state)
    applied: list[str] = []
    dropped: dict[str, str] = {}
    tip = state.get("autofix_sha")
    if ship:
        round_no = state.get("round", 1)
        applied, dropped = create_branch_with_patches(
            ctx.repo_path,
            ctx.head_sha,
            autofix_branch(state),
            [(f.finding_id, f.patch) for f in ship],
            f"pr-agent round {round_no}: fix {', '.join(f.finding_id for f in ship)}",
        )
        if applied:
            tip = rev_parse(ctx.repo_path, autofix_branch(state))
    record = {
        "round": state.get("round", 1),
        "head_sha": ctx.head_sha,
        "findings": state.get("final_findings", []),
        "decisions": state.get("decisions", []),
        "fixes": state.get("fixes", []),
        "verifications": state.get("verifications", []),
        "approved": state.get("approved") or [],
        "applied": applied,
        "dropped": dropped,
    }
    return {"history": [record], "autofix_sha": tip}
