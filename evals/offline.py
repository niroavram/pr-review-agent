"""ScriptedLLM: replays a case's canned LLM outputs (demo/cases/NN/offline.json).

The rest of the pipeline (git, analyzers, verification, policy) runs for real, so offline
evals measure everything except LLM judgement.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from pr_agent.agents.llm import load_prompt
from pr_agent.demo import render

T = TypeVar("T", bound=BaseModel)

KINDS = ("security", "bug", "conventions")


def load_fixture(case_dir: Path) -> dict[str, Any]:
    """offline.json with {{SECRET_HEX}} rendered for this case (empty if missing)."""
    path = case_dir / "offline.json"
    if not path.exists():
        return {}
    data: dict[str, Any] = json.loads(render(path.read_text(), case_dir.name))
    return data


def reviewer_kind(role: str, system: str) -> str | None:
    """`review:<kind>` roles name the kind; plain `review` is detected from the prompt."""
    if role.startswith("review:"):
        return role.split(":", 1)[1]
    for kind in KINDS:
        if system.startswith(load_prompt(kind).strip()):
            return kind
    head = system[:300].lower()
    if "conventions.md" in head:
        return "conventions"
    if "security" in head:
        return "security"
    if "bug" in head:
        return "bug"
    return None


class ScriptedLLM:
    """Implements the LLM protocol from a fixture:

    {"reviews": {"security": [LLMFinding...], "bug": [...], "conventions": [...]},
     "fixes": {"<file>:<line>": {"edits": [...], "explanation": "..."}},
     "critic": {"verdict": "accept"}}
    """

    def __init__(self, fixture: dict[str, Any]) -> None:
        self.fixture = fixture
        self.calls: list[dict[str, str]] = []

    @classmethod
    def for_case(cls, case_dir: Path) -> ScriptedLLM:
        return cls(load_fixture(case_dir))

    def structured(self, schema: type[T], system: str, user: str, *, role: str) -> T:
        self.calls.append({"schema": schema.__name__, "role": role})
        return schema.model_validate(self._payload(schema.__name__, system, user, role))

    def _payload(self, name: str, system: str, user: str, role: str) -> dict[str, Any]:
        if name == "ReviewOutput":
            kind = reviewer_kind(role, system)
            reviews = self.fixture.get("reviews", {})
            return {"findings": reviews.get(kind, []) if kind else []}
        if name == "FixOutput":
            return self._fix(user)
        if name == "CriticOutput":
            critic: dict[str, Any] = self.fixture.get("critic", {"verdict": "accept"})
            return critic
        return {}

    def _fix(self, user: str) -> dict[str, Any]:
        """The fix keyed by the `<file>:<line>` in the user message, else the nearest line in
        the same file."""
        fixes: dict[str, dict[str, Any]] = self.fixture.get("fixes", {})
        for key, fix in fixes.items():
            if re.search(rf"(?m)^{re.escape(key)}\b", user):
                return fix
        best: tuple[int, dict[str, Any]] | None = None
        for key, fix in fixes.items():
            file, _, line = key.rpartition(":")
            m = re.search(rf"(?m)^{re.escape(file)}:(\d+)", user)
            if m and line.isdigit():
                distance = abs(int(m.group(1)) - int(line))
                if best is None or distance < best[0]:
                    best = (distance, fix)
        return best[1] if best else {}
