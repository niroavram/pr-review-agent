"""`.pr-agent.yml` schema and loader. Always loaded from the BASE sha; failures fail closed."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from pr_agent.gitutil import show_file

CONFIG_FILE = ".pr-agent.yml"
TEMPLATE = Path(__file__).resolve().parents[3] / "templates" / CONFIG_FILE

LevelName = Literal["auto", "suggest", "comment", "forbidden"]
Sensitivity = Literal["low", "medium", "high", "critical"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PathRule(_Strict):
    match: list[str]
    sensitivity: Sensitivity
    owners: list[str] = []
    reason: str | None = None


class RouteRule(_Strict):
    match: str  # "POST /v1/payments/*", "* /v1/admin/*"
    sensitivity: Sensitivity
    owners: list[str] = []
    reason: str | None = None


class Limits(_Strict):
    auto_max_lines: int = 20
    auto_max_files: int = 3


class LintRules(_Strict):
    auto: list[str] = []
    suggest: list[str] = []
    comment: list[str] = []
    forbidden: list[str] = []


class Conventions(_Strict):
    file: str = "CONVENTIONS.md"


class AutonomyConfig(_Strict):
    version: Literal[1]
    levels: dict[Sensitivity, LevelName]
    default_sensitivity: Sensitivity = "medium"
    limits: Limits = Limits()
    paths: list[PathRule] = []
    routes: list[RouteRule] = []
    fix_types: dict[
        Literal["format", "lint", "typo", "bug", "security", "public_api_change"], LevelName
    ] = {}
    lint_rules: LintRules = LintRules()
    conventions: Conventions = Conventions()

    @field_validator("levels")
    @classmethod
    def _all_levels(cls, v: dict[str, str]) -> dict[str, str]:
        missing = {"low", "medium", "high", "critical"} - set(v)
        if missing:
            raise ValueError(f"levels missing: {sorted(missing)}")
        return v


def parse_config(text: str) -> AutonomyConfig:
    """Raises ValueError with a readable message on any problem."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ValueError(f"invalid YAML: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("config must be a mapping")
    try:
        return AutonomyConfig.model_validate(data)
    except ValidationError as e:
        errs = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())
        raise ValueError(errs) from e


def load_base_config(repo: str | Path, base_sha: str) -> tuple[AutonomyConfig | None, str | None]:
    """(config, None) on success; (None, reason) when missing/invalid -> caller fails closed."""
    text = show_file(repo, base_sha, CONFIG_FILE)
    if text is None:
        return None, f"{CONFIG_FILE} not found on base branch"
    try:
        return parse_config(text), None
    except ValueError as e:
        return None, f"{CONFIG_FILE} invalid on base branch: {e}"
