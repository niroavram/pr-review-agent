"""LangGraph state. Fan-out nodes append via reducers; everything else is last-write-wins."""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from pr_agent.models import (
    Finding,
    FixProposal,
    PolicyDecision,
    PRContext,
    RuleProposal,
    Verification,
)


def merge_dicts(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    return {**(left or {}), **(right or {})}


class ReviewState(TypedDict, total=False):
    ctx: PRContext
    config: dict[str, Any] | None  # AutonomyConfig.model_dump(); None = fail-closed
    config_error: str | None
    conventions: str  # base-branch CONVENTIONS.md text
    triage: dict[str, Any]  # {"reviewers": [...], "skipped_files": [...], "notes": [...]}
    findings: Annotated[list[Finding], operator.add]  # raw, from fan-out branches
    tool_status: Annotated[dict[str, str], merge_dicts]  # {"gitleaks": "skipped: not installed"}
    final_findings: list[Finding]  # after aggregate (ids assigned)
    fixes: Annotated[list[FixProposal], operator.add]  # critic-accepted proposals
    verifications: Annotated[list[Verification], operator.add]
    decisions: list[PolicyDecision]
    approved: list[str]  # finding ids approved at the interrupt
    rule_proposals: list[RuleProposal]
    banners: Annotated[list[str], operator.add]  # warnings shown at the top of the review
    output_dir: str


class FixTask(TypedDict):
    """Payload sent (via Send) into the per-finding fix pipeline."""

    finding: Finding
    ctx: PRContext
    config: dict[str, Any] | None
    conventions: str
