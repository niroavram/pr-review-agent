"""Runtime settings from environment (.env is loaded by the CLI)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    review_model: str = field(
        default_factory=lambda: _env("PR_AGENT_REVIEW_MODEL", "claude-sonnet-5-5")
    )
    fix_model: str = field(default_factory=lambda: _env("PR_AGENT_FIX_MODEL", "claude-opus-5-5"))
    min_confidence: float = field(
        default_factory=lambda: float(_env("PR_AGENT_MIN_CONFIDENCE", "0.6"))
    )
    max_comments: int = field(default_factory=lambda: int(_env("PR_AGENT_MAX_COMMENTS", "15")))
    max_fixes: int = field(default_factory=lambda: int(_env("PR_AGENT_MAX_FIXES", "8")))
    max_revisions: int = 2
    max_rule_proposals: int = 3
    # auto | docker | local
    sandbox: str = field(default_factory=lambda: _env("PR_AGENT_SANDBOX", "auto"))
    work_dir: Path = field(default_factory=lambda: Path(_env("PR_AGENT_HOME", ".pr-agent")))
    tool_timeout: int = 120
    test_timeout: int = 300
