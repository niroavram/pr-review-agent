"""Registry of static analyzers. Each takes an AnalysisContext and returns findings.

An analyzer raises ToolUnavailable when its tool is not installed (reported as skipped) and
any other exception when the tool failed (reported as an error). Neither sinks the review.
"""

from __future__ import annotations

from collections.abc import Callable

from pr_agent.analyzers.bandit import run_bandit
from pr_agent.analyzers.base import AnalysisContext, ToolUnavailable
from pr_agent.analyzers.gitleaks import run_gitleaks
from pr_agent.analyzers.ruff import run_ruff
from pr_agent.analyzers.semgrep import run_semgrep
from pr_agent.models import Finding

Analyzer = Callable[[AnalysisContext], list[Finding]]

ANALYZERS: dict[str, Analyzer] = {
    "ruff": run_ruff,
    "bandit": run_bandit,
    "semgrep": run_semgrep,
    "gitleaks": run_gitleaks,
}

__all__ = ["ANALYZERS", "AnalysisContext", "Analyzer", "ToolUnavailable", "run_all"]


def run_all(actx: AnalysisContext) -> tuple[list[Finding], dict[str, str]]:
    """Run every analyzer, isolating failures. Returns (findings, {name: status}).

    status is "ok", "skipped: <why>" (tool not installed) or "error: <message>".
    """
    findings: list[Finding] = []
    status: dict[str, str] = {}
    for name, analyzer in ANALYZERS.items():
        try:
            findings += analyzer(actx)
            status[name] = "ok"
        except ToolUnavailable as e:
            status[name] = f"skipped: {e}"
        except Exception as e:  # one broken tool must not sink the review
            status[name] = f"error: {e}"
    return findings, status
