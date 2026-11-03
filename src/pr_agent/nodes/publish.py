"""Publish node: autofix branch + review.md, patches/ and review.json in the run directory."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableConfig

from pr_agent.deps import get_deps
from pr_agent.models import FixProposal, Level
from pr_agent.publish.git_branch import create_branch_with_patches
from pr_agent.publish.markdown import render_review
from pr_agent.state import ReviewState
from pr_agent.tracing import redact, redact_text


def _run_id(state: ReviewState) -> str:
    if state.get("output_dir"):
        return Path(state["output_dir"]).name
    ctx = state["ctx"]
    return f"{ctx.pr_id}-{ctx.head_sha[:8]}"


def _to_ship(state: ReviewState) -> list[FixProposal]:
    """AUTO fixes, or approved SUGGEST fixes, whose verification passed."""
    levels = {d.finding_id: d.level for d in state.get("decisions", [])}
    passed = {v.finding_id for v in state.get("verifications", []) if v.passed}
    approved = set(state.get("approved", []))

    def ships(fid: str) -> bool:
        level = levels.get(fid)
        return level is Level.AUTO or (level is Level.SUGGEST and fid in approved)

    return [
        f
        for f in state.get("fixes", [])
        if f.patch and ships(f.finding_id) and f.finding_id in passed
    ]


def _summary_json(
    state: ReviewState, applied: list[str], dropped: dict[str, str], branch: str | None
) -> dict[str, Any]:
    def dump(items: list[Any]) -> list[Any]:
        return [x.model_dump(mode="json") for x in items]

    decisions = [
        {**d.model_dump(mode="json"), "level": d.level.label} for d in state.get("decisions", [])
    ]
    return redact(
        {
            "ctx": state["ctx"].model_dump(mode="json", exclude={"diff"}),
            "findings": dump(state.get("final_findings", [])),
            "fixes": dump(state.get("fixes", [])),
            "verifications": dump(state.get("verifications", [])),
            "decisions": decisions,
            "applied": applied,
            "dropped": dropped,
            "banners": state.get("banners", []),
            "tool_status": state.get("tool_status", {}),
            "rule_proposals": dump(state.get("rule_proposals", [])),
            "config_error": state.get("config_error"),
            "autofix_branch": branch,
        }
    )


def publish(state: ReviewState, config: RunnableConfig) -> dict[str, Any]:
    """Ship eligible fixes to autofix/<pr_id> and write the review artifacts."""
    ctx = state["ctx"]
    run_id = _run_id(state)
    out = get_deps(config).settings.work_dir / "runs" / run_id
    ship = _to_ship(state)
    branch = f"autofix/{ctx.pr_id}"
    applied: list[str] = []
    dropped: dict[str, str] = {}
    if ship:
        applied, dropped = create_branch_with_patches(
            ctx.repo_path,
            ctx.head_sha,
            branch,
            [(f.finding_id, f.patch) for f in ship],
            f"pr-agent autofix for {ctx.pr_id}: {', '.join(f.finding_id for f in ship)}",
        )

    (out / "patches").mkdir(parents=True, exist_ok=True)
    md = render_review(state, applied=applied, dropped=dropped, run_id=run_id)
    (out / "review.md").write_text(md)
    for fix in state.get("fixes", []):
        if fix.patch:
            (out / "patches" / f"{fix.finding_id}.patch").write_text(redact_text(fix.patch))
    summary = _summary_json(state, applied, dropped, branch if applied else None)
    (out / "review.json").write_text(json.dumps(summary, indent=2))
    return {"output_dir": str(out)}
