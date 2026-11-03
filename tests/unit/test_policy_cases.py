"""Policy decisions for the eval cases, on a real git repo, real ASTs and real unified diffs."""

import difflib
import shutil
from pathlib import Path
from typing import Any

import pytest

from pr_agent.gitutil import git, rev_parse
from pr_agent.models import Finding, FixProposal, Level, PRContext, Verification
from pr_agent.nodes.gate import policy_gate
from pr_agent.policy.config import TEMPLATE, AutonomyConfig, load_base_config, parse_config
from pr_agent.policy.engine import decide, pre_ceiling
from pr_agent.policy.facts import PatchFacts, finding_facts, patch_facts

DEMO_BASE = Path(__file__).parents[2] / "demo" / "base"
IDENT = ["-c", "user.name=t", "-c", "user.email=t@example.invalid"]
PAY = ["@payments-team"]
OK = Verification(finding_id="F1", passed=True)


def commit(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, *IDENT, "commit", "-q", "-m", message)
    return rev_parse(repo, "HEAD")


@pytest.fixture(scope="module")
def ctx(tmp_path_factory: pytest.TempPathFactory) -> PRContext:
    """Demo shop at head, with an unused import in scripts/report.py for the F401 case."""
    repo = tmp_path_factory.mktemp("cases") / "repo"
    shutil.copytree(DEMO_BASE, repo)
    report = repo / "scripts" / "report.py"
    report.write_text(
        report.read_text().replace("from src.store import", "import os\nfrom src.store import")
    )
    git(repo, "init", "-q", "-b", "main")
    sha = commit(repo, "head")
    return PRContext(repo_path=str(repo), repo_name="demo", pr_id="1", base_sha=sha, head_sha=sha)


@pytest.fixture(scope="module")
def cfg() -> AutonomyConfig:
    return parse_config(TEMPLATE.read_text())


def head(ctx: PRContext, path: str) -> str:
    return (Path(ctx.repo_path) / path).read_text()


def udiff(path: str, before: str, after: str) -> str:
    lines = difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True), f"a/{path}", f"b/{path}"
    )
    return "".join(lines)


def edit(ctx: PRContext, path: str, old: str, new: str) -> str:
    """Unified diff replacing `old` with `new` in the head version of `path`."""
    before = head(ctx, path)
    assert old in before
    return udiff(path, before, before.replace(old, new, 1))


def finding(file: str, line: int = 1, **kw: Any) -> Finding:
    data: dict[str, Any] = {"source": "llm:bug", "category": "bug", "message": "m", **kw}
    return Finding(id="F1", file=file, line=line, **data)


def lint(file: str, rule: str = "ruff:F401", line: int = 1) -> Finding:
    return finding(file, line, source="ruff", category="lint", rule_id=rule)


def proposal(patch: str, fix_type: str = "lint") -> FixProposal:
    return FixProposal(finding_id="F1", patch=patch, fix_type=fix_type)  # type: ignore[arg-type]


def decide_patch(ctx: PRContext, cfg: AutonomyConfig | None, f: Finding, patch: str) -> Any:
    return decide(f, proposal(patch), OK, cfg, patch_facts(ctx, patch))


REPORT_F401 = ("import os\n", "")


def test_case09_payments_bug_is_forbidden_and_never_proposed(
    ctx: PRContext, cfg: AutonomyConfig
) -> None:
    f = finding("src/payments/charges.py", line=4)
    patch = edit(
        ctx,
        "src/payments/charges.py",
        "(total_cents * percent) // 100",
        "total_cents * percent // 100",
    )
    d = decide_patch(ctx, cfg, f, patch)
    assert d.level is Level.FORBIDDEN and d.owners == PAY
    assert "src/payments/**" in d.decided_by
    assert pre_ceiling(f, cfg, ctx) is Level.FORBIDDEN  # graph never starts a fix pipeline

    state: Any = {
        "ctx": ctx,
        "config": cfg.model_dump(),
        "final_findings": [f],
        "fixes": [proposal(patch, "bug")],
        "verifications": [OK],
    }
    out = policy_gate(state, {"configurable": {}})  # would raise if it tried to interrupt
    assert out["decisions"][0].level is Level.FORBIDDEN and out["approved"] == []


def test_case10_pr_cannot_lower_its_own_policy(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src" / "payments").mkdir(parents=True)
    (repo / ".pr-agent.yml").write_text(TEMPLATE.read_text())
    (repo / "src" / "payments" / "charges.py").write_text("def charge(x):\n    return x\n")
    git(repo, "init", "-q", "-b", "main")
    base = commit(repo, "base")
    git(repo, "checkout", "-q", "-b", "lower-policy")
    lowered = TEMPLATE.read_text().replace("sensitivity: critical", "sensitivity: low")
    (repo / ".pr-agent.yml").write_text(lowered)
    head_sha = commit(repo, "payments are low risk now")

    cfg, err = load_base_config(repo, base)
    assert cfg is not None and err is None
    assert parse_config(lowered).paths[0].sensitivity == "low"  # what the PR wanted
    ctx = PRContext(
        repo_path=str(repo), repo_name="r", pr_id="10", base_sha=base, head_sha=head_sha
    )
    f = finding("src/payments/charges.py", line=2)
    patch = udiff(
        "src/payments/charges.py",
        "def charge(x):\n    return x\n",
        "def charge(x):\n    return x + 0\n",
    )
    d = decide_patch(ctx, cfg, f, patch)
    assert d.level is Level.FORBIDDEN and d.decided_by == 'paths[0] "src/payments/**" -> critical'
    # and an agent patch that edits the policy file is itself forbidden
    edit_cfg = udiff(".pr-agent.yml", TEMPLATE.read_text(), lowered)
    assert (
        decide_patch(ctx, cfg, lint("docs/x.md"), edit_cfg).decided_by == "hard_rule:no_policy_edit"
    )


def test_case11_unused_import_in_scripts_is_auto(ctx: PRContext, cfg: AutonomyConfig) -> None:
    patch = edit(ctx, "scripts/report.py", *REPORT_F401)
    facts = patch_facts(ctx, patch)
    assert facts.lines_changed == 1 and facts.routes == [] and facts.api_changes == []
    d = decide(lint("scripts/report.py", line=3), proposal(patch), OK, cfg, facts)
    assert d.level is Level.AUTO and d.decided_by == 'paths[3] "scripts/**" -> low'


def test_case12_mixed_patch_takes_most_restrictive_path(
    ctx: PRContext, cfg: AutonomyConfig
) -> None:
    patch = edit(ctx, "scripts/report.py", *REPORT_F401) + edit(
        ctx, "src/payments/charges.py", "percent is 0-100", "percent is 0..100"
    )
    d = decide_patch(ctx, cfg, lint("scripts/report.py", line=3), patch)
    assert d.level is Level.FORBIDDEN and d.owners == PAY
    assert d.decided_by == 'paths[0] "src/payments/**" -> critical'


def test_lint_fix_inside_payments_route_is_forbidden(ctx: PRContext, cfg: AutonomyConfig) -> None:
    routes_py = head(ctx, "src/api/routes.py")
    old = '    return {"id": row[0], "total_cents": apply_discount(row[2], percent)}'
    new = '    return {"id": row[0], "total_cents": apply_discount(row[2], percent=percent)}'
    line = routes_py.splitlines().index(old) + 1
    f = lint("src/api/routes.py", rule="ruff:UP035", line=line)
    d = decide_patch(ctx, cfg, f, edit(ctx, "src/api/routes.py", old, new))
    assert d.level is Level.FORBIDDEN and d.owners == PAY
    assert d.decided_by == 'routes[0] "POST /v1/payments/*" -> critical'

    # without a patch, the route around the finding line still tags the owners
    assert pre_ceiling(f, cfg) is Level.SUGGEST  # path alone: src/api/** is medium
    assert pre_ceiling(f, cfg, ctx) is Level.FORBIDDEN
    d = decide(f, None, None, cfg, finding_facts(ctx, f))
    assert d.level is Level.FORBIDDEN and d.owners == PAY

    # a lint fix in the public GET route stays at the path level (medium -> suggest)
    public = edit(
        ctx, "src/api/routes.py", 'return {"error": "not found"}', "return {'error': 'not found'}"
    )
    assert (
        decide_patch(ctx, cfg, lint("src/api/routes.py", "ruff:UP035"), public).level
        is Level.SUGGEST
    )


def test_public_api_change_caps_low_path(ctx: PRContext, cfg: AutonomyConfig) -> None:
    patch = edit(
        ctx, "scripts/report.py", "def main() -> None:", "def main(argv: list[str]) -> None:"
    )
    facts = patch_facts(ctx, patch)
    assert facts.api_changes == [
        "scripts/report.py: changed main: main() -> None -> main(argv) -> None"
    ]
    d = decide(lint("scripts/report.py"), proposal(patch), OK, cfg, facts)
    assert d.level is Level.COMMENT and d.decided_by == "fix_types.public_api_change -> comment"


def test_added_skip_marker_is_forbidden(ctx: PRContext, cfg: AutonomyConfig) -> None:
    patch = edit(
        ctx, "tests/test_charges.py", "def test_discount", "@pytest.mark.skip\ndef test_discount"
    )
    d = decide_patch(ctx, cfg, lint("tests/test_charges.py"), patch)
    assert d.level is Level.FORBIDDEN and d.decided_by == "hard_rule:no_test_skip"


def test_fail_closed_without_config(ctx: PRContext) -> None:
    auto_patch = edit(ctx, "scripts/report.py", *REPORT_F401)
    d = decide_patch(ctx, None, lint("scripts/report.py"), auto_patch)
    assert d.level is Level.SUGGEST and d.decided_by == "fail_closed: no valid base config"
    skip = edit(
        ctx, "tests/test_charges.py", "def test_discount", "@pytest.mark.skip\ndef test_discount"
    )
    assert decide_patch(ctx, None, lint("tests/x.py"), skip).decided_by == "hard_rule:no_test_skip"
    d = decide(lint("scripts/report.py"), None, None, None, PatchFacts(paths=["scripts/report.py"]))
    assert d.level is Level.COMMENT and d.decided_by == "no verified patch"
