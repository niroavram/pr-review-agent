"""Per-finding fix pipeline nodes: propose -> critic -> (propose | verify | done)."""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.runnables import RunnableConfig

from pr_agent.agents.critic import critique
from pr_agent.agents.fixer import propose_fix
from pr_agent.deps import get_deps
from pr_agent.models import Finding, FixProposal, PRContext, Verification
from pr_agent.settings import Settings


class FixState(TypedDict, total=False):
    """State of the fix subgraph for one finding."""

    max_revisions: int  # set by the graph from Settings

    finding: Finding
    ctx: PRContext
    config: dict[str, Any] | None
    conventions: str
    proposal: FixProposal | None
    attempts: int
    feedback: str
    verdict: str
    fixes: Annotated[list[FixProposal], operator.add]
    verifications: Annotated[list[Verification], operator.add]


def boundaries_text(config: dict[str, Any] | None) -> str:
    """Short, human-readable summary of autonomy limits for the fixer prompt (context only)."""
    if not config:
        return "No valid autonomy config: nothing is applied automatically (fail closed)."
    levels = ", ".join(f"{k}={v}" for k, v in config.get("levels", {}).items())
    limits = config.get("limits", {})
    lines = [
        f"Sensitivity levels: {levels}.",
        f"Auto-applied fixes must touch at most {limits.get('auto_max_lines', '?')} lines "
        f"in at most {limits.get('auto_max_files', '?')} files.",
    ]
    fix_types = config.get("fix_types", {})
    if fix_types:
        lines.append("Fix types: " + ", ".join(f"{k}={v}" for k, v in fix_types.items()) + ".")
    return "\n".join(lines)


def propose(state: FixState, config: RunnableConfig) -> dict[str, Any]:
    """Ask the fixer for a patch, passing the critic's last feedback."""
    attempts = state.get("attempts", 0) + 1
    try:
        proposal = propose_fix(
            state["finding"],
            state["ctx"],
            get_deps(config).llm,
            boundaries=boundaries_text(state.get("config")),
            feedback=state.get("feedback", ""),
        )
    except Exception as e:
        return {
            "proposal": None,
            "verdict": "reject",
            "feedback": f"fixer error: {e}",
            "attempts": attempts,
        }
    if proposal is None:
        return {
            "proposal": None,
            "verdict": "reject",
            "feedback": "could not build patch",
            "attempts": attempts,
        }
    return {"proposal": proposal.model_copy(update={"attempts": attempts}), "attempts": attempts}


def critic(state: FixState, config: RunnableConfig) -> dict[str, Any]:
    """Judge the proposal and record the verdict on a copy of it."""
    proposal = state.get("proposal")
    if proposal is None:
        return {"verdict": "reject"}
    out = critique(state["finding"], proposal, state["ctx"], get_deps(config).llm)
    reviewed = proposal.model_copy(
        update={"critic_verdict": out.verdict, "critic_notes": out.notes}
    )
    return {"verdict": out.verdict, "feedback": out.notes, "proposal": reviewed}


def route_after_critic(state: FixState) -> Literal["propose", "verify", "done"]:
    """accept -> verify; revise within the revision budget -> propose; else done."""
    budget = state.get("max_revisions", Settings().max_revisions)
    verdict = state.get("verdict")
    if verdict == "accept":
        return "verify"
    if verdict == "revise" and state.get("attempts", 0) <= budget:
        return "propose"
    return "done"


def done(state: FixState, config: RunnableConfig) -> dict[str, Any]:
    """Record a rejected (or out-of-revisions) attempt so the report can show it."""
    proposal = state.get("proposal")
    if proposal is None:
        return {}
    return {"fixes": [proposal.model_copy(update={"critic_verdict": "reject"})]}
