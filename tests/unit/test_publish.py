import json
from pathlib import Path

import pytest

from pr_agent.deps import Deps
from pr_agent.gitutil import git, rev_parse, show_file
from pr_agent.ingest.local import load_local
from pr_agent.models import (
    Finding,
    FixProposal,
    Level,
    PolicyDecision,
    PRContext,
    RuleProposal,
    Verification,
)
from pr_agent.nodes.publish import publish
from pr_agent.publish.git_branch import create_branch_with_patches
from pr_agent.publish.markdown import render_review
from pr_agent.settings import Settings
from pr_agent.state import ReviewState
from tests.fakes import FakeLLM

BRANCH = "case/01-sql-injection"

FIX_PATCH = """\
--- a/src/store/orders.py
+++ b/src/store/orders.py
@@ -19,3 +19,3 @@
 def find_orders_by_customer(conn: sqlite3.Connection, customer: str) -> list[tuple[int, int]]:
-    query = f"SELECT id, total_cents FROM orders WHERE customer = '{customer}'"
-    return conn.execute(query).fetchall()
+    query = "SELECT id, total_cents FROM orders WHERE customer = ?"
+    return conn.execute(query, (customer,)).fetchall()
"""

CONFLICT_PATCH = """\
--- a/src/store/orders.py
+++ b/src/store/orders.py
@@ -1,1 +1,1 @@
-import this_line_does_not_exist
+import os
"""


def _ctx(pr_id: str = "42") -> PRContext:
    return PRContext(
        repo_path="/r", repo_name="shop", pr_id=pr_id, base_sha="b" * 40, head_sha="a" * 40
    )


def _finding(n: int, rule: str | None = "conv:CONV-004") -> Finding:
    return Finding(
        id=f"F{n}",
        source="llm:conventions",
        rule_id=rule,
        category="security",
        severity="high",
        file="src/store/orders.py",
        line=20,
        message="SQL built with an f-string",
    )


def _state(level: Level, **extra: object) -> ReviewState:
    state: ReviewState = {
        "ctx": _ctx(),
        "final_findings": [_finding(1)],
        "decisions": [
            PolicyDecision(
                finding_id="F1",
                level=level,
                decided_by='paths[0] "src/payments/**" -> critical',
                reason="Money movement",
                owners=["@payments-team", "@sec"],
            )
        ],
        "fixes": [
            FixProposal(
                finding_id="F1",
                patch=FIX_PATCH,
                explanation="Use a bound parameter.",
                fix_type="security",
            )
        ],
        "verifications": [Verification(finding_id="F1", passed=True, checks={"applies": True})],
    }
    state.update(extra)  # type: ignore[typeddict-item]
    return state


def test_render_no_findings() -> None:
    md = render_review({"ctx": _ctx(), "final_findings": [], "banners": ["> careful"]})
    assert "No issues found." in md and "## PR review: shop #42" in md
    assert "### Findings" not in md and "### Fixes" not in md


def test_render_header_table_and_tools() -> None:
    state = _state(
        Level.SUGGEST, tool_status={"gitleaks": "skipped: not installed"}, banners=["B!"]
    )
    md = render_review(state, run_id="run-1")
    assert md.index("## PR review") < md.index("> B!") < md.index("finding(s)")
    assert "`aaaaaaaa`" in md and "gitleaks" in md and "skipped: not installed" in md
    assert "| F1 | high | `src/store/orders.py:20` | conv:CONV-004 |" in md


def test_render_auto_applied() -> None:
    md = render_review(_state(Level.AUTO), applied=["F1"])
    assert "F1: auto" in md and "Applied to `autofix/42`" in md and "```diff" in md


def test_render_suggest_pending_and_approved() -> None:
    md = render_review(_state(Level.SUGGEST), run_id="run-1")
    assert "```diff" in md and "pr-agent resume run-1 --approve F1" in md
    assert "Decided by" in md and "Money movement" in md
    md = render_review(_state(Level.SUGGEST, approved=["F1"]), run_id="run-1")
    assert "Approved." in md and "--approve" not in md


def test_render_comment_has_no_patch() -> None:
    md = render_review(_state(Level.COMMENT))
    assert "Use a bound parameter." in md and "```diff" not in md


def test_render_forbidden_tags_owners() -> None:
    md = render_review(_state(Level.FORBIDDEN))
    assert "No patch. Owners: @payments-team @sec" in md and "```diff" not in md


def test_render_failed_verification_and_rule_proposals() -> None:
    proposals = [
        RuleProposal(
            finding_id="F1",
            kind="semgrep_rule",
            rule_id="custom:SEC-2",
            content="x",
            valid=True,
            note="0 base hits",
        ),
        RuleProposal(
            finding_id="F1", kind="convention", rule_id="CONV-099", content="y", valid=False
        ),
    ]
    state = _state(
        Level.SUGGEST,
        verifications=[
            Verification(
                finding_id="F1", passed=False, checks={"applies": True, "tests_pass": False}
            )
        ],
        rule_proposals=proposals,
    )
    md = render_review(state)
    assert "Verification failed: tests_pass." in md
    assert "### Prevent this next time" in md and "custom:SEC-2" in md and "0 base hits" in md
    assert "CONV-099" not in md


def test_render_redacts_secrets() -> None:
    from pr_agent.demo import demo_secret

    secret = demo_secret("publish-test")
    state = _state(Level.COMMENT)
    state["final_findings"] = [_finding(1).model_copy(update={"message": f'api_key = "{secret}"'})]
    assert secret not in render_review(state)


@pytest.fixture
def user_branch(demo_repo: Path) -> str:
    return git(demo_repo, "symbolic-ref", "--short", "HEAD").strip()


def test_create_branch_applies_and_drops(demo_repo: Path, user_branch: str) -> None:
    head = rev_parse(demo_repo, BRANCH)
    applied, dropped = create_branch_with_patches(
        demo_repo,
        head,
        "autofix/test-git-branch",
        [("F1", FIX_PATCH), ("F2", CONFLICT_PATCH)],
        "fix",
    )
    assert applied == ["F1"] and set(dropped) == {"F2"} and dropped["F2"]
    content = show_file(demo_repo, "autofix/test-git-branch", "src/store/orders.py") or ""
    assert "(customer,)" in content
    assert rev_parse(demo_repo, "autofix/test-git-branch^") == head
    assert git(demo_repo, "symbolic-ref", "--short", "HEAD").strip() == user_branch
    assert git(demo_repo, "status", "--porcelain") == ""
    assert "pr-agent-wt-" not in git(demo_repo, "worktree", "list")


def test_create_branch_nothing_applies_creates_no_branch(demo_repo: Path) -> None:
    head = rev_parse(demo_repo, BRANCH)
    applied, dropped = create_branch_with_patches(
        demo_repo, head, "autofix/test-none", [("F2", CONFLICT_PATCH)], "fix"
    )
    assert applied == [] and "F2" in dropped
    assert git(demo_repo, "branch", "--list", "autofix/test-none") == ""


def test_publish_node_writes_outputs(demo_repo: Path, tmp_path: Path, user_branch: str) -> None:
    ctx = load_local(demo_repo, head=BRANCH).model_copy(update={"pr_id": "test-publish-node"})
    state = _state(Level.AUTO, ctx=ctx, banners=["note"])
    deps = Deps(llm=FakeLLM(), settings=Settings(work_dir=tmp_path))
    out = publish(state, {"configurable": {"deps": deps}})

    run_dir = Path(out["output_dir"])
    assert run_dir == tmp_path / "runs" / f"test-publish-node-{ctx.head_sha[:8]}"
    assert "Applied to `autofix/test-publish-node`" in (run_dir / "review.md").read_text()
    assert (run_dir / "patches" / "F1.patch").read_text() == FIX_PATCH
    data = json.loads((run_dir / "review.json").read_text())
    assert data["applied"] == ["F1"] and data["autofix_branch"] == "autofix/test-publish-node"
    assert data["decisions"][0]["level"] == "auto" and "diff" not in data["ctx"]
    assert data["findings"][0]["id"] == "F1"
    assert "(customer,)" in (
        show_file(demo_repo, "autofix/test-publish-node", "src/store/orders.py") or ""
    )
    assert git(demo_repo, "symbolic-ref", "--short", "HEAD").strip() == user_branch


def test_publish_node_skips_unapproved_suggest(demo_repo: Path, tmp_path: Path) -> None:
    ctx = load_local(demo_repo, head=BRANCH).model_copy(update={"pr_id": "test-publish-suggest"})
    state = _state(Level.SUGGEST, ctx=ctx, output_dir=str(tmp_path / "x" / "my-run"))
    deps = Deps(llm=FakeLLM(), settings=Settings(work_dir=tmp_path))
    out = publish(state, {"configurable": {"deps": deps}})
    assert Path(out["output_dir"]).name == "my-run"
    data = json.loads((Path(out["output_dir"]) / "review.json").read_text())
    assert data["applied"] == [] and data["autofix_branch"] is None
    assert "--approve F1" in (Path(out["output_dir"]) / "review.md").read_text()
    assert git(demo_repo, "branch", "--list", "autofix/test-publish-suggest") == ""
