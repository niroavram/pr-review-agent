"""Facts about a proposed patch that the policy engine needs: paths, size, routes, API, rules.

`diff_facts` is pure (diff text only). `patch_facts` / `finding_facts` also read file contents
at the PR head (the tree the patch applies to) so routes and public signatures can be checked.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from unidiff import PatchedFile, PatchSet, UnidiffParseError

from pr_agent.gitutil import show_file
from pr_agent.models import Finding, PRContext
from pr_agent.policy.api_diff import public_api_changes
from pr_agent.policy.hard_rules import hard_rule_violations, is_test_file
from pr_agent.policy.routes import Route, touched_routes


@dataclass
class PatchFacts:
    paths: list[str]  # every touched path (both sides of a rename)
    changed_lines: dict[str, set[int]] = field(default_factory=dict)  # path -> touched lines
    lines_changed: int = 0  # added + removed
    routes: list[Route] = field(default_factory=list)  # routes whose handler was touched
    api_changes: list[str] = field(default_factory=list)  # changed/removed public signatures
    hard_rules: list[tuple[str, str]] = field(default_factory=list)  # (rule, detail)


def _parse(patch: str) -> list[PatchedFile]:
    """Files of a unified diff; [] if malformed (hard rules report that separately)."""
    try:
        return list(PatchSet(patch))
    except UnidiffParseError:
        return []


def _strip(path: str) -> str:
    return path.removeprefix("a/").removeprefix("b/")


def patch_paths(patch: str) -> list[str]:
    """Repo-relative files touched by a unified diff (both sides of a rename); [] if malformed."""
    paths: list[str] = []
    for pf in _parse(patch):
        for p in (_strip(pf.source_file), _strip(pf.target_file)):
            if p != "/dev/null" and p not in paths:
                paths.append(p)
    return paths


def _lines(pf: PatchedFile) -> tuple[set[int], set[int]]:
    """(removed lines numbered in the old file, added lines numbered in the new file)."""
    lines = [ln for hunk in pf for ln in hunk]
    removed = {ln.source_line_no for ln in lines if ln.is_removed and ln.source_line_no}
    added = {ln.target_line_no for ln in lines if ln.is_added and ln.target_line_no}
    return removed, added


def apply_hunks(before: str, pf: PatchedFile) -> str:
    """New content of one file: keep untouched lines, drop removed ones, insert added ones."""
    old = before.splitlines(keepends=True)
    out: list[str] = []
    pos = 0  # next unread index in `old`
    for hunk in pf:
        # "-3,0" (pure insertion) means "after line 3"; otherwise the hunk starts at line 3
        start = hunk.source_start - 1 if hunk.source_length else hunk.source_start
        out += old[pos:start]
        pos = start
        for line in hunk:
            if line.is_context or line.is_removed:
                pos += 1
            if line.is_context or line.is_added:
                out.append(line.value)
    return "".join(out + old[pos:])


def diff_facts(patch: str) -> PatchFacts:
    """Everything knowable from the diff text alone (no routes or API diff)."""
    facts = PatchFacts(paths=patch_paths(patch), hard_rules=hard_rule_violations(patch))
    for pf in _parse(patch):
        removed, added = _lines(pf)
        facts.changed_lines[pf.path] = removed | added
        facts.lines_changed += len(removed) + len(added)
    return facts


def patch_facts(ctx: PRContext, patch: str) -> PatchFacts:
    """diff_facts plus routes and public API changes, using the head content of each file."""
    facts = diff_facts(patch)
    for pf in _parse(patch):
        if not pf.path.endswith(".py"):
            continue
        old_path = _strip(pf.source_file)
        before = "" if pf.is_added_file else show_file(ctx.repo_path, ctx.head_sha, old_path)
        if before is None:  # cannot see the file: fail closed
            facts.routes.append(Route("*", "", 0, 0, resolved=False))
            facts.api_changes.append(f"{pf.path}: head content unavailable")
            continue
        after = "" if pf.is_removed_file else apply_hunks(before, pf)
        removed, added = _lines(pf)
        # removed lines live in the old file, added lines in the new one
        for route in touched_routes(before, removed) + touched_routes(after, added):
            if route not in facts.routes:
                facts.routes.append(route)
        if not is_test_file(pf.path):  # test functions are not a public API
            facts.api_changes += [f"{pf.path}: {c}" for c in public_api_changes(before, after)]
    return facts


def finding_facts(ctx: PRContext, finding: Finding) -> PatchFacts:
    """Facts for a finding without a patch: its file, plus the route around its line (head)."""
    head = show_file(ctx.repo_path, ctx.head_sha, finding.file)
    routes = touched_routes(head, {finding.line}) if head and finding.file.endswith(".py") else []
    return PatchFacts(paths=[finding.file], routes=routes)
