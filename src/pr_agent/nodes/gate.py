"""Policy gate: decide an autonomy level per finding, then pause for human approval of SUGGESTs."""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from pr_agent.models import Finding, FixProposal, Level, PolicyDecision, Verification
from pr_agent.policy.config import AutonomyConfig
from pr_agent.policy.engine import decide
from pr_agent.state import ReviewState


def latest_by_finding(
    fixes: list[FixProposal], verifications: list[Verification]
) -> tuple[dict[str, FixProposal], dict[str, Verification]]:
    """Latest non-rejected fix and latest verification per finding id (later entries win)."""
    proposals = {f.finding_id: f for f in fixes if f.critic_verdict != "reject"}
    checked = {v.finding_id: v for v in verifications}
    return proposals, checked


def policy_gate(state: ReviewState, config: RunnableConfig) -> dict:
    """Decide every final finding; interrupt once for approval when there are SUGGEST fixes."""
    cfg_data = state.get("config")
    cfg = AutonomyConfig.model_validate(cfg_data) if cfg_data else None
    findings = state.get("final_findings", [])
    proposals, checked = latest_by_finding(state.get("fixes", []), state.get("verifications", []))
    decisions = [decide(f, proposals.get(f.id), checked.get(f.id), cfg) for f in findings]
    candidates = [
        f
        for f, d in zip(findings, decisions, strict=True)
        if d.level is Level.SUGGEST and (v := checked.get(f.id)) is not None and v.passed
    ]
    candidate_ids = {f.id for f in candidates}
    approved: Any = state.get("approved")
    if candidates and approved is None:
        approved = interrupt({"suggest": [_summary(f) for f in candidates]})
    approved = [i for i in (approved or []) if i in candidate_ids]
    _trace(decisions, proposals)
    return {"decisions": decisions, "approved": approved}


def _summary(f: Finding) -> dict[str, str]:
    """What a human needs to approve or skip one suggested fix."""
    return {"id": f.id, "file": f.file, "message": f.message}


def _trace(decisions: list[PolicyDecision], proposals: dict[str, FixProposal]) -> None:
    """Attach decisions to the current LangSmith run, if tracing is on. Never raises."""
    try:
        from langsmith.run_helpers import get_current_run_tree

        rt = get_current_run_tree()
        if rt is None:
            return
        rt.add_metadata(
            {
                "policy_decisions": [
                    {"finding": d.finding_id, "level": d.level.label, "decided_by": d.decided_by}
                    for d in decisions
                ]
            }
        )
        patched = [d for d in decisions if d.finding_id in proposals]
        tags = []
        if any(d.level is Level.FORBIDDEN for d in decisions) or any(
            d.level is Level.COMMENT for d in patched
        ):
            tags.append("policy:blocked")  # a patch existed but policy withheld it
        if any(d.level is Level.SUGGEST for d in patched):
            tags.append("policy:downgraded")  # a patch exists but needs human approval
        if tags:
            rt.add_tags(tags)
    except Exception:
        return
