"""Deterministic autonomy policy: each constraint proposes a level; the most restrictive wins.

Pure functions only (no I/O, no LLM), so every decision is reproducible from its inputs.
File contents arrive pre-computed in PatchFacts (see facts.py); the engine never reads git.
"""

from __future__ import annotations

from collections.abc import Callable
from fnmatch import fnmatchcase
from functools import lru_cache

import pathspec

from pr_agent.models import (
    Finding,
    FixProposal,
    Level,
    PolicyDecision,
    PRContext,
    Verification,
    fix_type_for,
)
from pr_agent.policy.config import AutonomyConfig
from pr_agent.policy.facts import PatchFacts, diff_facts, finding_facts
from pr_agent.policy.facts import patch_paths as patch_paths  # re-export: nodes/verify.py uses it
from pr_agent.policy.routes import route_level

# (level, decided_by, reason, owners)
Constraint = tuple[Level, str, str, list[str]]
ConstraintFn = Callable[
    [Finding, FixProposal | None, Verification | None, AutonomyConfig, PatchFacts],
    Constraint | None,
]

FAIL_CLOSED = "fail_closed: no valid base config"


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


def _strictest(items: list[tuple[Level, str, list[str]]], reason: str) -> Constraint | None:
    """Most restrictive of several (level, decided_by, owners); owners from all are unioned."""
    if not items:
        return None
    level, by, _ = max(items, key=lambda x: x[0])  # max() keeps the first tie
    owners: list[str] = []
    for _l, _b, item_owners in items:
        owners += [o for o in item_owners if o not in owners]
    return level, by, reason, owners


def default_facts(finding: Finding, proposal: FixProposal | None) -> PatchFacts:
    """Facts from the diff alone (or just the finding's file) when the caller had no repo."""
    return diff_facts(proposal.patch) if proposal else PatchFacts(paths=[finding.file])


def pre_ceiling(
    finding: Finding, cfg: AutonomyConfig | None, ctx: PRContext | None = None
) -> Level:
    """Level from the finding's location alone; lets the graph skip fixes for comment/forbidden.

    With ctx, the route around the finding's line (at head) counts too.
    """
    if cfg is None:
        return Level.SUGGEST
    facts = finding_facts(ctx, finding) if ctx else PatchFacts(paths=[finding.file])
    found = [
        location(finding, None, None, cfg, facts),
        touched_route(finding, None, None, cfg, facts),
    ]
    return max(c[0] for c in found if c is not None)


def hard_rules(
    _f: Finding, _p: FixProposal | None, _v: Verification | None, _c: object, facts: PatchFacts
) -> Constraint | None:
    """Non-configurable rules (hard_rules.py); the first violation is reported."""
    if not facts.hard_rules:
        return None
    details = "; ".join(f"{name}: {detail}" for name, detail in facts.hard_rules)
    return Level.FORBIDDEN, f"hard_rule:{facts.hard_rules[0][0]}", details, []


def location(
    finding: Finding,
    _p: FixProposal | None,
    _v: Verification | None,
    cfg: AutonomyConfig,
    facts: PatchFacts,
) -> Constraint | None:
    """Most restrictive level over the touched files (the finding's file without a patch)."""
    paths = facts.paths or [finding.file]
    items = [path_level(p, cfg) for p in paths]
    return _strictest(items, f"location: {', '.join(paths)}")


def touched_route(
    _f: Finding,
    _p: FixProposal | None,
    _v: Verification | None,
    cfg: AutonomyConfig,
    facts: PatchFacts,
) -> Constraint | None:
    """Most restrictive level over the HTTP routes whose handler the patch touches."""
    names = ", ".join(f"{r.method} {r.path or '?'}" for r in facts.routes)
    return _strictest([route_level(r, cfg) for r in facts.routes], f"routes: {names}")


def fix_type_cap(
    finding: Finding,
    _p: FixProposal | None,
    _v: Verification | None,
    cfg: AutonomyConfig,
    _facts: PatchFacts,
) -> Constraint | None:
    """Max autonomy allowed for this kind of fix (derived from the finding, not the LLM)."""
    fix_type = fix_type_for(finding)
    name = cfg.fix_types.get(fix_type)
    if name is None:
        return None
    return Level.parse(name), f"fix_types.{fix_type} -> {name}", f"fix type {fix_type}", []


def public_api_cap(
    _f: Finding,
    _p: FixProposal | None,
    _v: Verification | None,
    cfg: AutonomyConfig,
    facts: PatchFacts,
) -> Constraint | None:
    """A patch that changes or removes a public signature is a public_api_change fix."""
    name = cfg.fix_types.get("public_api_change")
    if not facts.api_changes or name is None:
        return None
    by = f"fix_types.public_api_change -> {name}"
    return Level.parse(name), by, "; ".join(facts.api_changes), []


LINT_LISTS = ("auto", "suggest", "comment", "forbidden")  # least to most restrictive


def lint_rule_cap(
    finding: Finding,
    _p: FixProposal | None,
    _v: Verification | None,
    cfg: AutonomyConfig,
    _facts: PatchFacts,
) -> Constraint | None:
    """Per-rule cap for lint findings: strictest matching list wins; unlisted -> suggest."""
    rule_id = finding.rule_id
    if rule_id is None or fix_type_for(finding) != "lint":
        return None
    reason = f"lint rule {rule_id}"
    for name in reversed(LINT_LISTS):  # most restrictive first
        pattern = next((p for p in getattr(cfg.lint_rules, name) if fnmatchcase(rule_id, p)), None)
        if pattern is not None:
            return Level.parse(name), f'lint_rules.{name} "{pattern}" -> {name}', reason, []
    return Level.SUGGEST, f"lint_rules: unlisted {rule_id} -> suggest", reason, []


def limits(
    _f: Finding,
    proposal: FixProposal | None,
    _v: Verification | None,
    cfg: AutonomyConfig,
    facts: PatchFacts,
) -> Constraint | None:
    """Big patches are never AUTO. Returning SUGGEST under max() only ever lowers AUTO."""
    if proposal is None:
        return None
    lim = cfg.limits
    if facts.lines_changed > lim.auto_max_lines:
        reason = f"{facts.lines_changed} lines changed"
        return Level.SUGGEST, f"limits.auto_max_lines ({lim.auto_max_lines})", reason, []
    if len(facts.paths) > lim.auto_max_files:
        reason = f"{len(facts.paths)} files changed"
        return Level.SUGGEST, f"limits.auto_max_files ({lim.auto_max_files})", reason, []
    return None


def verified_patch(
    finding: Finding,
    proposal: FixProposal | None,
    verification: Verification | None,
    _cfg: object,
    _facts: PatchFacts,
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


# Order only matters for ties: the first constraint at the winning level names the decision.
CONSTRAINTS: list[ConstraintFn] = [
    hard_rules,
    location,
    touched_route,
    fix_type_cap,
    public_api_cap,
    lint_rule_cap,
    limits,
    verified_patch,
]


def decide(
    finding: Finding,
    proposal: FixProposal | None,
    verification: Verification | None,
    cfg: AutonomyConfig | None,
    facts: PatchFacts | None = None,
) -> PolicyDecision:
    """Apply all constraints and keep the most restrictive (first one wins ties).

    `facts` comes from facts.patch_facts / finding_facts; without it we use the diff alone.
    """
    facts = facts or default_facts(finding, proposal)
    if cfg is None:  # fail closed, but hard rules and "no verified patch" still apply
        results: list[Constraint | None] = [
            hard_rules(finding, proposal, verification, None, facts),
            (Level.SUGGEST, FAIL_CLOSED, ".pr-agent.yml missing or invalid on base", []),
            verified_patch(finding, proposal, verification, None, facts),
        ]
    else:
        results = [c(finding, proposal, verification, cfg, facts) for c in CONSTRAINTS]
    found = [r for r in results if r is not None]
    level, decided_by, reason, _ = max(found, key=lambda r: r[0])  # max() keeps the first tie
    owners: list[str] = []
    for r in found:
        owners += [o for o in r[3] if o not in owners]
    return PolicyDecision(
        finding_id=finding.id, level=level, decided_by=decided_by, reason=reason, owners=owners
    )
