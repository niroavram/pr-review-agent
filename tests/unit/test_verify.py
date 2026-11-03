import difflib
from pathlib import Path

import pytest
from langchain_core.runnables import RunnableConfig

from pr_agent.deps import Deps
from pr_agent.gitutil import rev_parse, show_file
from pr_agent.models import Finding, FixProposal, PRContext, Verification
from pr_agent.nodes.verify import verify_fix
from pr_agent.sandbox import LocalSandbox
from pr_agent.settings import Settings
from tests.fakes import FakeLLM

CASE = "case/01-sql-injection"
FILE = "src/store/orders.py"
VULN = """    query = f"SELECT id, total_cents FROM orders WHERE customer = '{customer}'"
    return conn.execute(query).fetchall()
"""
FIXED = """    query = "SELECT id, total_cents FROM orders WHERE customer = ?"
    return conn.execute(query, (customer,)).fetchall()
"""
STILL_VULN = """    sql = f"SELECT id, total_cents FROM orders WHERE customer = '{customer}'"
    return conn.execute(sql).fetchall()
"""
BROKEN = """    return []
"""

FINDING = Finding(
    id="F1",
    source="bandit",
    rule_id="bandit:B608",
    category="security",
    file=FILE,
    line=20,
    message="Possible SQL injection",
)


@pytest.fixture
def head(demo_repo: Path) -> str:
    content = show_file(demo_repo, rev_parse(demo_repo, CASE), FILE)
    assert content and VULN in content
    return content


def _diff(old: str, new: str) -> str:
    lines = difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True), f"a/{FILE}", f"b/{FILE}"
    )
    return "".join(lines)


def _verify(demo_repo: Path, tmp_path: Path, patch: str, mode: str = "local") -> dict:
    ctx = PRContext(
        repo_path=str(demo_repo),
        repo_name="demo",
        pr_id=CASE,
        base_sha=rev_parse(demo_repo, "main"),
        head_sha=rev_parse(demo_repo, CASE),
        mode=mode,  # type: ignore[arg-type]
    )
    proposal = FixProposal(finding_id="F1", patch=patch, fix_type="security")
    deps = Deps(llm=FakeLLM(), sandbox=LocalSandbox(), settings=Settings(work_dir=tmp_path))
    config: RunnableConfig = {"configurable": {"deps": deps}}
    state = {"finding": FINDING, "ctx": ctx, "config": None, "proposal": proposal}
    return verify_fix(state, config)


def _verification(out: dict) -> Verification:
    [v] = out["verifications"]
    assert v.finding_id == "F1" and out["fixes"][0].finding_id == "F1"
    return v


def test_correct_fix_passes_all_checks(demo_repo: Path, tmp_path: Path, head: str) -> None:
    v = _verification(_verify(demo_repo, tmp_path, _diff(head, head.replace(VULN, FIXED))))
    assert v.checks == {
        "applies": True,
        "finding_gone": True,
        "no_new_findings": True,
        "tests_pass": True,
    }
    assert v.passed


def test_patch_that_does_not_apply(demo_repo: Path, tmp_path: Path, head: str) -> None:
    wrong_base = head.replace("customer: str)", "name: str)")
    v = _verification(_verify(demo_repo, tmp_path, _diff(wrong_base, wrong_base + "# x\n")))
    assert v.checks == {"applies": False} and not v.passed and "git apply" in v.log


def test_fix_that_keeps_fstring(demo_repo: Path, tmp_path: Path, head: str) -> None:
    v = _verification(_verify(demo_repo, tmp_path, _diff(head, head.replace(VULN, STILL_VULN))))
    assert v.checks["applies"] and not v.checks["finding_gone"] and not v.passed


def test_fix_that_breaks_tests(demo_repo: Path, tmp_path: Path, head: str) -> None:
    v = _verification(_verify(demo_repo, tmp_path, _diff(head, head.replace(VULN, BROKEN))))
    assert v.checks["finding_gone"] and not v.checks["tests_pass"] and not v.passed


def test_tests_skipped_for_untrusted_code(demo_repo: Path, tmp_path: Path, head: str) -> None:
    patch = _diff(head, head.replace(VULN, FIXED))
    v = _verification(_verify(demo_repo, tmp_path, patch, mode="github"))
    assert "tests_pass" not in v.checks and v.passed and "skipped" in v.log


def test_no_proposal_returns_nothing(tmp_path: Path) -> None:
    assert verify_fix({"proposal": None}, {"configurable": {}}) == {}
