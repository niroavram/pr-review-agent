"""LLM reviewers (security, bug, conventions) that turn a PR into Findings."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from pr_agent import gitutil
from pr_agent.agents.llm import UNTRUSTED_NOTICE, load_prompt, untrusted
from pr_agent.deps import LLM
from pr_agent.models import Category, Finding, PRContext, Severity

ReviewerKind = Literal["security", "bug", "conventions"]
MAX_FILE_LINES = 400


class LLMFinding(BaseModel):
    """One problem as reported by the model."""

    file: str
    line: int
    end_line: int | None = None
    severity: Severity = "medium"
    category: Category = "bug"
    message: str
    confidence: float = 0.5
    rule_id: str | None = None


class ReviewOutput(BaseModel):
    """Structured reviewer output; empty means the PR is clean."""

    findings: list[LLMFinding] = []


def _numbered(text: str, limit: int = MAX_FILE_LINES) -> str:
    """Prefix lines with head line numbers and truncate long files."""
    lines = text.splitlines()
    out = [f"{i:>4}| {line}" for i, line in enumerate(lines[:limit], start=1)]
    if len(lines) > limit:
        out.append(f"... truncated ({len(lines) - limit} more lines)")
    return "\n".join(out)


def build_user_message(kind: ReviewerKind, ctx: PRContext, conventions: str) -> str:
    """PR metadata, diff and head files (all untrusted) plus trusted base conventions."""
    parts = [
        untrusted("pr_title", ctx.title),
        untrusted("pr_description", ctx.description),
        "## Unified diff",
        untrusted("diff", ctx.diff),
        "## Changed files at HEAD (line-numbered)",
    ]
    for f in ctx.files:
        if f.status == "deleted" or not f.path.endswith(".py"):
            continue
        content = gitutil.show_file(ctx.repo_path, ctx.head_sha, f.path)
        if content is not None:
            parts.append(untrusted(f"file:{f.path}", _numbered(content)))
    if kind == "conventions":
        parts += ["## CONVENTIONS.md (trusted, from the base branch)", conventions]
    return "\n\n".join(parts)


def _category(kind: ReviewerKind, reported: Category) -> Category:
    """Security and conventions reviewers have a fixed category."""
    if kind == "security":
        return "security"
    if kind == "conventions":
        return "convention"
    return reported


def run_reviewer(kind: ReviewerKind, ctx: PRContext, conventions: str, llm: LLM) -> list[Finding]:
    """Run one reviewer and map its output to Findings in files this PR changed."""
    system = f"{load_prompt(kind)}\n\n{UNTRUSTED_NOTICE}"
    user = build_user_message(kind, ctx, conventions)
    out = llm.structured(ReviewOutput, system, user, role="review")
    changed = {f.path for f in ctx.files}
    return [
        Finding(
            source=f"llm:{kind}",
            rule_id=item.rule_id,
            category=_category(kind, item.category),
            severity=item.severity,
            file=item.file,
            line=item.line,
            end_line=item.end_line,
            message=item.message,
            confidence=min(max(item.confidence, 0.0), 1.0),
        )
        for item in out.findings
        if item.file in changed
    ]
