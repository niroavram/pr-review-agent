"""Graph node factory for the LLM reviewers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.runnables import RunnableConfig

from pr_agent.agents.reviewers import ReviewerKind, run_reviewer
from pr_agent.deps import get_deps
from pr_agent.state import ReviewState

ALL_REVIEWERS: list[str] = ["security", "bug", "conventions"]


def make_reviewer_node(kind: ReviewerKind) -> Callable[[ReviewState, RunnableConfig], dict]:
    """Build a node that runs one reviewer. It never raises, so the review never crashes."""

    def node(state: ReviewState, config: RunnableConfig) -> dict[str, Any]:
        if kind not in state.get("triage", {}).get("reviewers", ALL_REVIEWERS):
            return {"findings": []}
        try:
            llm = get_deps(config).llm
            findings = run_reviewer(kind, state["ctx"], state.get("conventions", ""), llm)
            return {"findings": findings}
        except Exception as e:
            return {"findings": [], "tool_status": {f"llm:{kind}": f"error: {e}"}}

    node.__name__ = f"review_{kind}"
    return node
