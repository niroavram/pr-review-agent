"""Bandit (Python security linter) runner: JSON output -> Finding objects."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pr_agent.models import Finding, Severity
from pr_agent.sandbox import Sandbox

_SEVERITY: dict[str, Severity] = {"LOW": "low", "MEDIUM": "medium", "HIGH": "high"}
_CONFIDENCE = {"LOW": 0.5, "MEDIUM": 0.8, "HIGH": 1.0}


def bandit_cmd(sandbox: Sandbox) -> list[str]:
    """Locally use this venv's bandit; inside a container rely on the image's `bandit`."""
    return [sys.executable, "-m", "bandit"] if sandbox.mode == "local" else ["bandit"]


def run_bandit(sandbox: Sandbox, workdir: Path, files: list[str]) -> list[Finding]:
    """Run bandit on `files` (relative to workdir). Raises RuntimeError if bandit itself fails."""
    files = [f for f in files if f.endswith(".py")]
    if not files:
        return []
    res = sandbox.run([*bandit_cmd(sandbox), "-q", "-f", "json", *files], workdir)
    if res.timed_out or res.returncode not in (0, 1):  # 1 = issues found, not an error
        raise RuntimeError(f"bandit exit {res.returncode}: {res.stderr.strip()[:300]}")
    return parse_bandit(res.stdout, workdir)


def parse_bandit(output: str, workdir: Path) -> list[Finding]:
    """Turn bandit's JSON report into findings with repo-relative paths."""
    try:
        results = json.loads(output).get("results", [])
    except json.JSONDecodeError as e:
        raise RuntimeError(f"bandit output is not JSON: {e}") from e
    return [
        Finding(
            source="bandit",
            rule_id=f"bandit:{r['test_id']}",
            category="security",
            severity=_SEVERITY.get(r.get("issue_severity", ""), "medium"),
            file=_relative(r["filename"], workdir),
            line=int(r.get("line_number", 1)),
            message=r.get("issue_text", ""),
            confidence=_CONFIDENCE.get(r.get("issue_confidence", ""), 0.5),
        )
        for r in results
    ]


def _relative(filename: str, workdir: Path) -> str:
    """Bandit echoes paths as given; normalise absolute or "./" paths to repo-relative."""
    path = Path(filename)
    if path.is_absolute():
        try:
            path = path.resolve().relative_to(workdir.resolve())
        except ValueError:
            pass
    return path.as_posix().removeprefix("./")
