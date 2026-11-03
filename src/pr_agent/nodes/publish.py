"""Publish node: autofix branch + review.md, patches/ and review.json in the run directory."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableConfig

from pr_agent.deps import get_deps
from pr_agent.nodes.apply import apply_fixes, autofix_branch
from pr_agent.publish.markdown import render_review
from pr_agent.rounds import merge_rounds
from pr_agent.state import ReviewState
from pr_agent.tracing import redact, redact_text


def _run_id(state: ReviewState) -> str:
    if state.get("output_dir"):
        return Path(state["output_dir"]).name
    ctx = state["ctx"]
    return f"{ctx.pr_id}-{ctx.head_sha[:8]}"


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
            "rounds": len(state.get("history", [])),
            "resolved_in_round": state.get("resolved_in_round", {}),
            "escalations": dump(state.get("escalations", [])),
            "escalation_replies": state.get("escalation_replies", {}),
        }
    )


def publish(state: ReviewState, config: RunnableConfig) -> dict[str, Any]:
    """Write review.md, patches/ and review.json for all rounds merged (latest record wins)."""
    run_id = _run_id(state)
    out = get_deps(config).settings.work_dir / "runs" / run_id
    history = state.get("history") or apply_fixes(state, config)["history"]  # single-round path
    view = merge_rounds(history)
    merged: ReviewState = {
        **state,
        "history": history,
        "final_findings": view.findings,
        "decisions": view.decisions,
        "fixes": view.fixes,
        "verifications": view.verifications,
        "approved": view.approved,
    }
    merged["resolved_in_round"] = view.resolved_in_round  # type: ignore[typeddict-unknown-key]
    branch = autofix_branch(state) if view.applied else None

    (out / "patches").mkdir(parents=True, exist_ok=True)
    md = render_review(merged, applied=view.applied, dropped=view.dropped, run_id=run_id)
    (out / "review.md").write_text(md)
    for fix in view.fixes:
        if fix.patch:
            (out / "patches" / f"{fix.finding_id}.patch").write_text(redact_text(fix.patch))
    summary = _summary_json(merged, view.applied, view.dropped, branch)
    (out / "review.json").write_text(json.dumps(summary, indent=2))
    return {"output_dir": str(out)}
