"""Seeded demo cases: they build, their fixtures are valid, and the deterministic ones pass
the evaluators end to end with canned LLM outputs (real git, analyzers, policy)."""

from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from evals.evaluators import evaluate_case
from evals.offline import ScriptedLLM, load_fixture, reviewer_kind
from evals.run import main, run_case
from evals.schema import ExpectedCase
from pr_agent.agents.critic import CriticOutput
from pr_agent.agents.fixer import FixOutput, apply_edits
from pr_agent.agents.llm import load_prompt
from pr_agent.agents.reviewers import ReviewOutput
from pr_agent.analyzers import ANALYZERS
from pr_agent.demo import DEMO_DIR, demo_secret, list_cases, load_case, render
from pr_agent.gitutil import git, show_file
from pr_agent.settings import Settings

CASES = list_cases()
CASE_IDS = [c.name for c in CASES]


def _case(prefix: str) -> Path:
    return next(c for c in CASES if c.name.startswith(prefix))


def _overlay(case_dir: Path) -> dict[str, str]:
    """Rendered overlay: {repo path: content}."""
    files = case_dir / "files"
    out = {}
    for p in sorted(x for x in files.rglob("*") if x.is_file()):
        rel = p.relative_to(files)
        if p.suffix == ".tmpl":
            out[str(rel.with_suffix(""))] = render(p.read_text(), case_dir.name)
        else:
            out[str(rel)] = p.read_text()
    return out


def test_twelve_cases() -> None:
    assert [c.name[:2] for c in CASES] == [f"{i:02d}" for i in range(1, 13)]


@pytest.mark.parametrize("case_dir", CASES, ids=CASE_IDS)
def test_case_builds_and_differs_from_main(demo_repo: Path, case_dir: Path) -> None:
    branch = load_case(case_dir)["branch"]
    head = git(demo_repo, "rev-parse", branch).strip()
    assert head != git(demo_repo, "rev-parse", "main").strip()
    assert git(demo_repo, "diff", "--name-only", "main", branch).strip()


@pytest.mark.parametrize("case_dir", CASES, ids=CASE_IDS)
def test_expected_json_validates(case_dir: Path) -> None:
    expected = ExpectedCase.model_validate(json.loads((case_dir / "expected.json").read_text()))
    assert expected.zero_findings == (not expected.findings)


@pytest.mark.parametrize("case_dir", CASES, ids=CASE_IDS)
def test_overlay_files_parse(case_dir: Path) -> None:
    for path, content in _overlay(case_dir).items():
        if path.endswith(".py"):
            ast.parse(content, filename=path)
        elif path.endswith((".yml", ".yaml")):
            assert isinstance(yaml.safe_load(content), dict)


@pytest.mark.parametrize("case_dir", CASES, ids=CASE_IDS)
def test_offline_fixture_is_valid_and_edits_apply(case_dir: Path) -> None:
    fixture = load_fixture(case_dir)
    assert set(fixture) <= {"reviews", "fixes", "critic"}
    for findings in fixture.get("reviews", {}).values():
        ReviewOutput.model_validate({"findings": findings})
    CriticOutput.model_validate(fixture.get("critic", {}))
    overlay = _overlay(case_dir)
    for key, fix in fixture.get("fixes", {}).items():
        out = FixOutput.model_validate(fix)
        sources = {
            e.file: overlay.get(e.file) or (DEMO_DIR / "base" / e.file).read_text()
            for e in out.edits
        }
        assert apply_edits(sources, out.edits) is not None, f"{key}: an edit does not apply"


def test_case02_renders_the_derived_secret(demo_repo: Path) -> None:
    content = show_file(demo_repo, "case/02-hardcoded-secret", "src/store/notify.py")
    assert content is not None
    assert content.count(demo_secret("02_hardcoded_secret")) == 2
    assert "{{SECRET_HEX}}" not in content


def test_no_hex_secret_committed_under_demo() -> None:
    root = DEMO_DIR.parent
    res = subprocess.run(
        ["git", "grep", "--untracked", "-n", "-I", "-E", "[0-9a-fA-F]{32}", "--", "demo"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 1, f"32-hex literal under demo/:\n{res.stdout}"


# --- ScriptedLLM ------------------------------------------------------------------------


def test_scripted_llm_reviewer_kind_from_role_or_prompt() -> None:
    assert reviewer_kind("review:bug", "") == "bug"
    for kind in ("security", "bug", "conventions"):
        assert reviewer_kind("review", load_prompt(kind) + "\n\nnotice") == kind


def test_scripted_llm_picks_fix_by_location() -> None:
    llm = ScriptedLLM(
        {
            "fixes": {
                "a.py:3": {"explanation": "three"},
                "a.py:30": {"explanation": "thirty"},
            }
        }
    )

    def pick(user: str) -> str:
        return llm.structured(FixOutput, "", user, role="fix").explanation

    assert pick("## Finding\na.py:30 [x] msg") == "thirty"
    assert pick("## Finding\na.py:3 [x] msg") == "three"
    assert pick("## Finding\na.py:28 [x] msg") == "thirty"  # nearest line in the file
    assert pick("## Finding\nb.py:3 [x] msg") == ""
    assert llm.structured(CriticOutput, "", "", role="critic").verdict == "accept"


# --- offline end to end -----------------------------------------------------------------

NO_RUFF = pytest.mark.xfail(
    "ruff" not in ANALYZERS,
    reason="src/ has no ruff analyzer / deterministic ruff fix yet (ANALYZERS has no 'ruff'), "
    "so the F401 finding is never produced",
    strict=False,
)
DETERMINISTIC = [
    pytest.param("01", id="01_sql_injection"),
    pytest.param("09", id="09_critical_path_bug"),
    pytest.param("10", id="10_config_tamper"),
    pytest.param("11", id="11_low_path_lint", marks=NO_RUFF),
    pytest.param("12", id="12_low_and_critical"),
]


@pytest.mark.parametrize("prefix", DETERMINISTIC)
def test_offline_case_passes_evaluators(demo_repo: Path, tmp_path: Path, prefix: str) -> None:
    case_dir = _case(prefix)
    expected = load_case(case_dir)["expected"]
    review = run_case(
        demo_repo, case_dir, ScriptedLLM.for_case(case_dir), Settings(work_dir=tmp_path)
    )
    results = evaluate_case(review, expected)
    failed = {k: r["comment"] for k, r in results.items() if r["score"] not in (None, 1.0)}
    assert not failed

    levels = {d["level"] for d in review["decisions"]}
    if prefix == "10":
        assert results["config_tamper_ignored"]["score"] == 1.0
        assert any(f["category"] == "config" for f in review["findings"])
    if prefix in ("09", "10", "12"):
        assert "forbidden" in levels and review["applied"] == []
        assert results["owners_tagged"]["score"] == 1.0
    if prefix == "12":
        assert review["fixes"], "a verified patch exists but policy withholds it"
    if prefix == "11":
        assert levels == {"auto"} and review["applied"]
        fixed = show_file(demo_repo, review["autofix_branch"], "scripts/report.py")
        assert fixed is not None and "import sys" not in fixed


def test_main_offline_writes_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PR_AGENT_HOME", str(tmp_path / "home"))
    out = main(offline=True, cases=["07"], results_path=tmp_path / "results.md")
    text = out.read_text()
    assert "Mode: offline" in text and "| 07_clean |" in text
