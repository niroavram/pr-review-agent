"""Turn raw fan-out findings into the short, ranked list a human will read."""

from __future__ import annotations

import re

from langchain_core.runnables import RunnableConfig

from pr_agent.deps import get_deps
from pr_agent.models import Finding
from pr_agent.state import ReviewState

_SEVERITY = {"critical": 0, "high": 1, "medium": 2, "low": 3}
_CONV_ID = re.compile(r"\bCONV-\d{3}\b")


def _is_tool(f: Finding) -> bool:
    return not f.source.startswith("llm:")


def _duplicate(a: Finding, b: Finding) -> bool:
    same_kind = a.category == b.category or {a.category, b.category} <= {"security", "bug"}
    return a.file == b.file and abs(a.line - b.line) <= 2 and same_kind


def _valid_convention(f: Finding, known_ids: set[str]) -> bool:
    """Convention findings must cite a CONV-ID that exists in the base CONVENTIONS.md."""
    if f.category != "convention":
        return True
    cited = (f.rule_id or "").removeprefix("conv:")
    return cited in known_ids


def aggregate(state: ReviewState, config: RunnableConfig) -> dict:
    settings = get_deps(config).settings
    known_ids = set(_CONV_ID.findall(state.get("conventions", "")))
    raw = [
        f
        for f in state.get("findings", [])
        # The confidence threshold filters LLM opinions; tool findings are evidence.
        if (_is_tool(f) or f.confidence >= settings.min_confidence)
        and _valid_convention(f, known_ids)
    ]
    # Tool findings first so they win dedupe (deterministic evidence beats LLM opinion).
    raw.sort(key=lambda f: (not _is_tool(f), _SEVERITY.get(f.severity, 9), -f.confidence))
    kept: list[Finding] = []
    for f in raw:
        if not any(_duplicate(f, k) for k in kept):
            kept.append(f)
    kept.sort(key=lambda f: (_SEVERITY.get(f.severity, 9), f.file, f.line))
    kept = kept[: settings.max_comments]
    final = [f.model_copy(update={"id": f"F{i}"}) for i, f in enumerate(kept, start=1)]
    return {"final_findings": final}
