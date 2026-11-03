"""Deterministic autonomy policy: each constraint proposes a level; the most restrictive wins.

Pure functions only (no I/O, no LLM), so every decision is reproducible from its inputs.
Later waves append more constraints (routes, hard rules, lint caps, limits) to CONSTRAINTS.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache

import pathspec
from unidiff import PatchSet, UnidiffParseError

from pr_agent.models import Finding, FixProposal, Level, PolicyDecision, Verification, fix_type_for
from pr_agent.policy.config import AutonomyConfig

# (level, decided_by, reason, owners)
Constraint = tuple[Level, str, str, list[str]]
ConstraintFn = Callable[
    [Finding, FixProposal | None, Verification | None, AutonomyConfig], Constraint | None
]

FAIL_CLOSED = "fail_closed: no valid base config"


def patch_paths(patch: str) -> list[str]:
    """Repo-relative files touched by a unified diff (both sides of a rename); [] if malformed."""
    try:
        patched = PatchSet(patch)
    except UnidiffParseError:
        return []
    paths: list[str] = []
    for pf in patched:
        for p in (pf.source_file, pf.target_file):
            p = p.removeprefix("a/").removeprefix("b/")
            if p != "/dev/null" and p not in paths:
                paths.append(p)
    return paths


@lru_cache(maxsize=256)
def _spec(pattern: str) -> pathspec.PathSpec:
    """Compiled gitignore-style (gitwildmatch) matcher for one pattern."""
    return pathspec.PathSpec.from_lines("gitignore", [pattern])


def path_level(path: str, cfg: AutonomyConfig) -> tuple[Level, str, list[str]]:
    """Level for one path. Several matching rules: most restrictive wins, owners are unioned."""
    best: tuple[Level, str] | None = None
    owners: list[str] = []
    for i, rule in enumerate(cfg.paths):
        pattern = next((p for p in rule.match if _spec(p).match_file(path)), None)
        if pattern is None:
            continue
        level = Level.parse(cfg.levels[rule.sensitivity])
        if best is None or level > best[0]:
            best = (level, f'paths[{i}] "{pattern}" -> {rule.sensitivity}')
        owners += [o for o in rule.owners if o not in owners]
    if best is None:
        level = Level.parse(cfg.levels[cfg.default_sensitivity])
        return level, f"default_sensitivity -> {cfg.default_sensitivity}", []
    return best[0], best[1], owners


def pre_ceiling(finding: Finding, cfg: AutonomyConfig | None) -> Level:
    """Level from the finding's file alone; lets the graph skip fixes for comment/forbidden."""
    return Level.SUGGEST if cfg is None else path_level(finding.file, cfg)[0]


def location(
    finding: Finding, proposal: FixProposal | None, _v: Verification | None, cfg: AutonomyConfig
) -> Constraint:
    """Most restrictive level over the patch's files (or the finding's file without a patch)."""
    paths = (patch_paths(proposal.patch) if proposal else []) or [finding.file]
    best: tuple[Level, str] | None = None
    owners: list[str] = []
    for path in paths:
        level, by, path_owners = path_level(path, cfg)
        if best is None or level > best[0]:
            best = (level, by)
        owners += [o for o in path_owners if o not in owners]
    assert best is not None  # paths always has at least finding.file
    return best[0], best[1], f"location: {', '.join(paths)}", owners


def fix_type_cap(
    finding: Finding, _p: FixProposal | None, _v: Verification | None, cfg: AutonomyConfig
) -> Constraint | None:
    """Max autonomy allowed for this kind of fix (derived from the finding, not the LLM)."""
    fix_type = fix_type_for(finding)
    name = cfg.fix_types.get(fix_type)
    if name is None:
        return None
    return Level.parse(name), f"fix_types.{fix_type} -> {name}", f"fix type {fix_type}", []


def verified_patch(
    finding: Finding,
    proposal: FixProposal | None,
    verification: Verification | None,
    _cfg: AutonomyConfig | None,
) -> Constraint | None:
    """Without a patch that passed verification we can only comment."""
    if not finding.fixable:
        reason = "finding is not fixable"
    elif proposal is None:
        reason = "no fix proposal"
    elif verification is None or not verification.passed:
        reason = "fix failed verification" if verification else "fix not verified"
    else:
        return None
    return Level.COMMENT, "no verified patch", reason, []


CONSTRAINTS: list[ConstraintFn] = [location, fix_type_cap, verified_patch]


def decide(
    finding: Finding,
    proposal: FixProposal | None,
    verification: Verification | None,
    cfg: AutonomyConfig | None,
) -> PolicyDecision:
    """Apply all constraints and keep the most restrictive (first one wins ties)."""
    if cfg is None:
        results: list[Constraint | None] = [
            (Level.SUGGEST, FAIL_CLOSED, ".pr-agent.yml missing or invalid on base", []),
            verified_patch(finding, proposal, verification, None),
        ]
    else:
        results = [c(finding, proposal, verification, cfg) for c in CONSTRAINTS]
    found = [r for r in results if r is not None]
    level, decided_by, reason, _ = max(found, key=lambda r: r[0])  # max() keeps the first tie
    owners: list[str] = []
    for r in found:
        owners += [o for o in r[3] if o not in owners]
    return PolicyDecision(
        finding_id=finding.id, level=level, decided_by=decided_by, reason=reason, owners=owners
    )
