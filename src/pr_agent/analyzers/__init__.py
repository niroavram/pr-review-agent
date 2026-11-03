"""Registry of static analyzers. Each takes (sandbox, workdir, files) and returns findings."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pr_agent.analyzers.bandit import run_bandit
from pr_agent.models import Finding
from pr_agent.sandbox import Sandbox

Analyzer = Callable[[Sandbox, Path, list[str]], list[Finding]]

ANALYZERS: dict[str, Analyzer] = {"bandit": run_bandit}
