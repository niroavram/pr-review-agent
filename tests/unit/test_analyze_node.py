from pathlib import Path

import pytest
from langchain_core.runnables import RunnableConfig

from pr_agent import analyzers
from pr_agent.deps import Deps
from pr_agent.gitutil import rev_parse
from pr_agent.models import ChangedFile, PRContext
from pr_agent.nodes.analyze import static_analysis
from pr_agent.sandbox import LocalSandbox
from pr_agent.settings import Settings
from tests.fakes import FakeLLM

CASE = "case/01-sql-injection"


def _config(tmp_path: Path) -> RunnableConfig:
    deps = Deps(llm=FakeLLM(), sandbox=LocalSandbox(), settings=Settings(work_dir=tmp_path))
    return {"configurable": {"deps": deps}}


def _ctx(repo: Path, added: list[int]) -> PRContext:
    return PRContext(
        repo_path=str(repo),
        repo_name="demo",
        pr_id=CASE,
        base_sha=rev_parse(repo, "main"),
        head_sha=rev_parse(repo, CASE),
        files=[
            ChangedFile(path="src/store/orders.py", added_lines=added),
            ChangedFile(path="tests/test_search.py", status="added", added_lines=[1, 2, 3]),
            ChangedFile(path="src/gone.py", status="deleted"),
        ],
    )


def test_finds_sql_injection_on_added_line(demo_repo: Path, tmp_path: Path) -> None:
    out = static_analysis({"ctx": _ctx(demo_repo, [17, 18, 19, 20, 21, 22])}, _config(tmp_path))
    status = out["tool_status"]
    assert status["bandit"] == status["ruff"] == status["semgrep"] == "ok"
    assert status["gitleaks"] in ("ok", "skipped: not installed")
    assert sorted((f.rule_id, f.file, f.line) for f in out["findings"]) == [
        ("bandit:B608", "src/store/orders.py", 20),
        ("semgrep:sql-built-from-string", "src/store/orders.py", 20),
    ]


def test_finding_outside_added_lines_is_dropped(demo_repo: Path, tmp_path: Path) -> None:
    out = static_analysis({"ctx": _ctx(demo_repo, [1, 2, 3])}, _config(tmp_path))
    assert out["findings"] == []


def test_broken_analyzer_reported_not_raised(
    demo_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(_: object) -> list:
        raise RuntimeError("crashed")

    monkeypatch.setitem(analyzers.ANALYZERS, "broken", broken)
    out = static_analysis({"ctx": _ctx(demo_repo, [20])}, _config(tmp_path))
    assert out["tool_status"]["broken"] == "error: crashed"
    assert out["tool_status"]["bandit"] == "ok" and len(out["findings"]) == 2
