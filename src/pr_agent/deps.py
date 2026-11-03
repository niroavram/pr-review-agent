"""Injected dependencies (LLM, sandbox, settings), passed via config["configurable"]["deps"]."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from pr_agent.sandbox import LocalSandbox, Sandbox
from pr_agent.settings import Settings

T = TypeVar("T", bound=BaseModel)


class LLM(Protocol):
    def structured(self, schema: type[T], system: str, user: str, *, role: str) -> T:
        """Return an instance of `schema`. role: "review" | "fix" | "critic" | "rule"."""
        ...


@dataclass
class Deps:
    llm: LLM
    sandbox: Sandbox = field(default_factory=LocalSandbox)
    settings: Settings = field(default_factory=Settings)
    interactive: bool = False


def get_deps(config: Any) -> Deps:
    return config["configurable"]["deps"]
