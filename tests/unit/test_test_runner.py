from pathlib import Path

from langchain_core.runnables import RunnableConfig

from pr_agent.deps import Deps
from pr_agent.models import PRContext
from pr_agent.nodes.tests import SKIPPED_BANNER, def_line, parse_failures
from pr_agent.nodes.tests import test_runner as run_tests_node
from pr_agent.sandbox import LocalSandbox, Sandbox
from pr_agent.settings import Settings
from tests.fakes import FakeLLM, FakeSandbox
from tests.unit._repo import make_pr

PYPROJECT = '[tool.pytest.ini_options]\npythonpath = ["."]\ntestpaths = ["tests"]\n'
CALC = "def add(a, b):\n    return a + b\n"
TESTS = """from src.calc import add


class TestCalc:
    def test_add(self):
        assert add(2, 2) == 4


def test_already_broken():
    assert 1 == 2
"""
BASE = {"pyproject.toml": PYPROJECT, "src/__init__.py": "", "src/calc.py": CALC}
BASE["tests/test_calc.py"] = TESTS


def _run(ctx: PRContext, tmp_path: Path, sandbox: Sandbox | None = None) -> dict:
    sandbox = sandbox or LocalSandbox()
    deps = Deps(llm=FakeLLM(), sandbox=sandbox, settings=Settings(work_dir=tmp_path))
    config: RunnableConfig = {"configurable": {"deps": deps}}
    return run_tests_node({"ctx": ctx}, config)


def test_introduced_failure_reported_pre_existing_not(tmp_path: Path) -> None:
    head = {"src/calc.py": CALC.replace("a + b", "a - b")}
    out = _run(make_pr(tmp_path / "repo", BASE, head), tmp_path)
    [f] = out["findings"]
    nodeid = "tests/test_calc.py::TestCalc::test_add"
    assert (f.source, f.rule_id, f.category, f.severity) == (
        "pytest",
        "pytest:failed",
        "test",
        "high",
    )
    assert (f.file, f.line, f.fixable) == ("tests/test_calc.py", 5, False)
    assert f.message.startswith(f"{nodeid} fails on this PR but passes on base: ")
    assert "assert 0 == 4" in f.message
    status = out["tool_status"]["pytest"]
    assert "1 introduced" in status and "test_already_broken" in status


def test_only_pre_existing_failure_gives_no_findings(tmp_path: Path) -> None:
    head = {"README.md": "docs only\n"}
    out = _run(make_pr(tmp_path / "repo", BASE, head), tmp_path)
    assert out["findings"] == []
    assert "0 introduced" in out["tool_status"]["pytest"]


def test_new_failing_test_counts_as_introduced(tmp_path: Path) -> None:
    head = {"tests/test_new.py": "def test_new():\n    assert False\n"}
    out = _run(make_pr(tmp_path / "repo", BASE, head), tmp_path)
    [f] = out["findings"]
    assert f.message.startswith("tests/test_new.py::test_new is new in this PR and fails")


def test_remote_code_unsandboxed_is_skipped(tmp_path: Path) -> None:
    ctx = make_pr(tmp_path / "repo", BASE, {"a.py": "x = 1\n"}, mode="github")
    out = _run(ctx, tmp_path)
    assert out["tool_status"] == {"pytest": "skipped: unsandboxed remote code"}
    assert out["banners"] == [SKIPPED_BANNER] and "findings" not in out


def test_remote_code_runs_in_isolated_sandbox(tmp_path: Path) -> None:
    ctx = make_pr(tmp_path / "repo", BASE, {"a.py": "x = 1\n"}, mode="github")
    sandbox = FakeSandbox()  # isolated; exit 0 = all tests pass
    out = _run(ctx, tmp_path, sandbox)
    assert out["tool_status"] == {"pytest": "ok"} and out["findings"] == []
    assert sandbox.commands[0][:3] == ["python", "-m", "pytest"]


def test_parse_failures_and_def_line(tmp_path: Path) -> None:
    out = "\n".join(
        [
            "F.",
            "FAILED tests/t.py::test_a[1-2] - assert 1 == 2",
            "ERROR tests/broken.py",
            "FAILED tests/t.py::test_a[1-2] - assert 1 == 2",
        ]
    )
    assert [(f.nodeid, f.reason) for f in parse_failures(out)] == [
        ("tests/t.py::test_a[1-2]", "assert 1 == 2"),
        ("tests/broken.py", ""),
    ]
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/t.py").write_text("import pytest\n\n\nasync def test_a(x):\n    pass\n")
    assert def_line(tmp_path, "tests/t.py::test_a[1-2]") == 4
    assert def_line(tmp_path, "tests/t.py::Missing::test_a") == 1
    assert def_line(tmp_path, "tests/gone.py::test_a") == 1
