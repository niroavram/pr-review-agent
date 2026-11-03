"""Ingest node: load the autonomy config and conventions from the BASE sha."""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from pr_agent.gitutil import show_file
from pr_agent.models import Finding
from pr_agent.policy.config import CONFIG_FILE, load_base_config
from pr_agent.state import ReviewState

CONFIG_CHANGED = (
    "This PR changes the autonomy config. Changes take effect only after merge; "
    "the base-branch config was applied to this review."
)


def ingest(state: ReviewState, config: RunnableConfig) -> dict[str, Any]:
    """Base-branch config (fail closed on error), conventions text, config-change notice."""
    ctx = state["ctx"]
    cfg, err = load_base_config(ctx.repo_path, ctx.base_sha)
    conv_file = cfg.conventions.file if cfg else "CONVENTIONS.md"
    out: dict[str, Any] = {
        "config": cfg.model_dump() if cfg else None,
        "config_error": err,
        "conventions": show_file(ctx.repo_path, ctx.base_sha, conv_file) or "",
        "banners": [],
    }
    if err:
        out["banners"] = [f"⚠️ Autonomy config: {err}. Failing closed: every fix is suggest-only."]
    if any(CONFIG_FILE in (f.path, f.old_path) for f in ctx.files):
        out["findings"] = [
            Finding(
                source="policy",
                category="config",
                severity="medium",
                file=CONFIG_FILE,
                line=1,
                message=CONFIG_CHANGED,
                fixable=False,
                confidence=1.0,
            )
        ]
    return out
