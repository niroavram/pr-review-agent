import json
from pathlib import Path

import pytest
from langchain_core.runnables import RunnableConfig

from pr_agent.analyzers import AnalysisContext, ToolUnavailable
from pr_agent.analyzers.gitleaks import STAGED_CONFIG, run_gitleaks
from pr_agent.deps import Deps
from pr_agent.nodes.analyze import static_analysis
from pr_agent.sandbox import ExecResult, LocalSandbox
from pr_agent.settings import Settings
from tests.fakes import FakeLLM, FakeSandbox
from tests.unit._repo import make_pr

# Assembled at runtime so no secret-looking literal is committed.
SECRET = "-".join(["not", "a", "real", "token"]) + "0123456789abcdef"


def _report(file: str = "src/settings.py") -> str:
    return json.dumps(
        [
            {
                "RuleID": "generic-api-key",
                "Description": "Detected a Generic API Key",
                "File": file,
                "StartLine": 3,
                "Secret": SECRET,
                "Match": f"API_KEY = '{SECRET}'",
            }
        ]
    )


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/settings.py").write_text(f"\n\nAPI_KEY = '{SECRET}'\n")
    (tmp_path / ".gitleaks.toml").write_text("# PR-supplied allowlist\n")
    return tmp_path


def test_parses_report_without_leaking_the_secret(workdir: Path) -> None:
    sandbox = FakeSandbox({"gitleaks": ExecResult(1, _report(), "")})
    [f] = run_gitleaks(AnalysisContext(workdir, None, ["src/settings.py"], sandbox))
    assert (f.source, f.rule_id, f.category, f.severity) == (
        "gitleaks",
        "gitleaks:generic-api-key",
        "security",
        "high",
    )
    assert (f.file, f.line) == ("src/settings.py", 3)
    assert f.message == "Possible secret: Detected a Generic API Key"
    assert SECRET not in f.model_dump_json()
    [cmd] = sandbox.commands
    assert cmd[:2] == ["gitleaks", "dir"] and "--redact" in cmd and "--config" not in cmd


def test_head_config_ignored_base_config_used(workdir: Path, tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir()
    (base / ".gitleaks.toml").write_text("# base config\n")
    seen: dict[str, list[str]] = {}

    class Recorder(FakeSandbox):
        def run(self, cmd: list[str], workdir: Path, timeout: int = 120) -> ExecResult:
            seen["files"] = sorted(p.name for p in workdir.rglob("*") if p.is_file())
            return super().run(cmd, workdir, timeout)

    sandbox = Recorder()
    files = ["src/settings.py", ".gitleaks.toml"]
    assert run_gitleaks(AnalysisContext(workdir, base, files, sandbox)) == []
    assert seen["files"] == [STAGED_CONFIG, "settings.py"]  # the head's .gitleaks.toml is gone
    assert sandbox.commands[0][-3:] == ["--config", STAGED_CONFIG, "."]


def test_missing_binary_raises_tool_unavailable(workdir: Path) -> None:
    sandbox = FakeSandbox({"gitleaks": ExecResult(127, "", "No such file: gitleaks")})
    with pytest.raises(ToolUnavailable, match="not installed"):
        run_gitleaks(AnalysisContext(workdir, None, ["src/settings.py"], sandbox))


def test_tool_error_is_runtime_error(workdir: Path) -> None:
    sandbox = FakeSandbox({"gitleaks": ExecResult(2, "", "bad flag")})
    with pytest.raises(RuntimeError, match="bad flag"):
        run_gitleaks(AnalysisContext(workdir, None, ["src/settings.py"], sandbox))


class NoGitleaksSandbox(LocalSandbox):
    """A real local sandbox on a machine where the gitleaks binary does not exist."""

    def run(self, cmd: list[str], workdir: Path, timeout: int = 120) -> ExecResult:
        if cmd[0] == "gitleaks":
            cmd = ["pr-agent-test-no-such-binary", *cmd[1:]]
        return super().run(cmd, workdir, timeout)


def test_analyze_node_reports_skipped(tmp_path: Path) -> None:
    pr = make_pr(tmp_path / "repo", base={"a.py": "x = 1\n"}, head={"a.py": "x = 2\n"})
    sandbox = NoGitleaksSandbox()
    deps = Deps(llm=FakeLLM(), sandbox=sandbox, settings=Settings(work_dir=tmp_path))
    config: RunnableConfig = {"configurable": {"deps": deps}}
    out = static_analysis({"ctx": pr}, config)
    assert out["tool_status"]["gitleaks"] == "skipped: not installed"
    assert out["tool_status"]["bandit"] == "ok"
