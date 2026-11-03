"""Turn raw fan-out findings into the short, ranked list a human will read.

Rules, in order:
1. LLM findings below `min_confidence` are dropped; tool findings are evidence and are kept.
2. Convention findings must cite a CONV-ID defined in the base CONVENTIONS.md.
3. Duplicates (same file, within 2 lines, same kind) collapse, preferring tool findings.
4. Sort by severity, then file and line; keep at most `max_comments`; ids F1, F2, ...
"""

from __future__ import annotations

import re

from langchain_core.runnables import RunnableConfig

from pr_agent.deps import get_deps
from pr_agent.models import Finding
from pr_agent.state import ReviewState

_SEVERITY = {"critical": 0, "high": 1, "medium": 2, "low": 3}
_CONV_ID = re.compile(r"\bCONV-\d{3}\b")


def _is_tool(f: Finding) -> bool:
    """Deterministic tool finding (bandit, ruff, ...) rather than an LLM opinion."""
    return not f.source.startswith("llm:")


def _duplicate(a: Finding, b: Finding) -> bool:
    """Same file, at most 2 lines apart, same category (security and bug count as one)."""
    same_kind = a.category == b.category or {a.category, b.category} <= {"security", "bug"}
    return a.file == b.file and abs(a.line - b.line) <= 2 and same_kind


def _valid_convention(f: Finding, known_ids: set[str]) -> bool:
    """Convention findings must cite a CONV-ID that exists in the base CONVENTIONS.md."""
    if f.category != "convention":
        return True
    cited = (f.rule_id or "").removeprefix("conv:")
    return cited in known_ids


def aggregate(state: ReviewState, config: RunnableConfig) -> dict:
    """Filter, dedupe, rank, cap and number the raw findings (see module docstring)."""
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
