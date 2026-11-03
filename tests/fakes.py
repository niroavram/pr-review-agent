"""Test doubles: no network, no API keys."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from pr_agent.sandbox import ExecResult

Responder = BaseModel | Callable[[str, str], BaseModel]


class FakeLLM:
    """Returns canned structured outputs keyed by schema class name.

    responses = {"ReviewOutput": [obj1, obj2], "CriticOutput": fn(system, user) -> obj}
    A list is consumed in order (last item repeats); a callable is called each time.
    """

    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[dict[str, str]] = []

    def structured(self, schema: type[BaseModel], system: str, user: str, *, role: str) -> Any:
        self.calls.append({"schema": schema.__name__, "role": role, "system": system, "user": user})
        r = self.responses.get(schema.__name__)
        if r is None:
            return schema.model_validate({})
        if callable(r) and not isinstance(r, BaseModel):
            return r(system, user)
        if isinstance(r, list):
            return r.pop(0) if len(r) > 1 else r[0]
        return r


class FakeSandbox:
    """Records commands; returns scripted results by first matching substring of the cmd."""

    mode = "fake"
    isolated = True

    def __init__(self, script: dict[str, ExecResult] | None = None) -> None:
        self.script = script or {}
        self.commands: list[list[str]] = []

    def run(self, cmd: list[str], workdir: Path, timeout: int = 120) -> ExecResult:
        self.commands.append(cmd)
        joined = " ".join(cmd)
        for key, result in self.script.items():
            if key in joined:
                return result
        return ExecResult(0, "", "")

    def python(self) -> list[str]:
        """Like a container: a bare interpreter name on PATH."""
        return ["python"]
