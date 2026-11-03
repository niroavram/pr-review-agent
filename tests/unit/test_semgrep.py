import json
import shutil
from pathlib import Path

from pr_agent.analyzers import ANALYZERS, AnalysisContext
from pr_agent.analyzers.base import CONFIG_DIR
from pr_agent.analyzers.semgrep import parse_semgrep, rule_id_and_category, run_semgrep
from pr_agent.gitutil import materialize
from pr_agent.sandbox import ExecResult, LocalSandbox
from tests.fakes import FakeSandbox
from tests.unit._repo import make_pr

BASE_RULES = (Path(__file__).parents[2] / "demo/base/.semgrep/custom.yml").read_text()
HEAD_RULES = """rules:
  - id: HEAD-ONLY
    message: a rule the PR added for itself
    languages: [python]
    severity: ERROR
    pattern: print(...)
"""
CODE = """def lookup(conn, name):
    try:
        print(name)
    except:
        pass
    return conn.execute(f"SELECT * FROM users WHERE name = '{name}'").fetchall()
"""


def test_registered() -> None:
    assert ANALYZERS["semgrep"] is run_semgrep


def test_real_semgrep_vendored_and_base_rules_only(tmp_path: Path) -> None:
    pr = make_pr(
        tmp_path / "repo",
        base={".semgrep/custom.yml": BASE_RULES},
        # The head ships its own .semgrep: it must be ignored. Deleting the base copy in the
        # PR must not disable it either.
        head={".semgrep/custom.yml": None, ".semgrep/head.yml": HEAD_RULES, "app.py": CODE},
    )
    workdir = materialize(pr.repo_path, pr.head_sha)
    base_dir = materialize(pr.repo_path, pr.base_sha)
    try:
        findings = run_semgrep(AnalysisContext(workdir, base_dir, ["app.py"], LocalSandbox()))
        assert not (workdir / CONFIG_DIR).exists()
    finally:
        shutil.rmtree(workdir)
        shutil.rmtree(base_dir)
    got = sorted((f.rule_id, f.category, f.file, f.line) for f in findings)
    assert got == [
        ("custom:ERR-001", "lint", "app.py", 2),
        ("semgrep:sql-built-from-string", "security", "app.py", 6),
    ]


def test_config_flags_are_local_only(tmp_path: Path) -> None:
    sandbox = FakeSandbox({"semgrep": ExecResult(0, '{"results": []}', "")})
    assert run_semgrep(AnalysisContext(tmp_path, None, ["a.py"], sandbox)) == []
    [cmd] = sandbox.commands
    configs = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "--config"]
    assert configs == [f"{CONFIG_DIR}/semgrep_vendored"]  # no auto, no registry, no base
    assert "--metrics=off" in cmd and cmd[0] == "semgrep"


def test_rule_id_mapping() -> None:
    assert rule_id_and_category("pr-agent-config.semgrep_vendored.eval-exec") == (
        "semgrep:eval-exec",
        "security",
    )
    assert rule_id_and_category("pr-agent-config.semgrep_custom.SEC-002") == (
        "custom:SEC-002",
        "security",
    )
    assert rule_id_and_category("pr-agent-config.semgrep_custom.NAMING-001") == (
        "custom:NAMING-001",
        "lint",
    )


def test_parse_severity_and_paths(tmp_path: Path) -> None:
    out = json.dumps(
        {
            "results": [
                {
                    "check_id": "x.semgrep_custom.NAMING-001",
                    "path": "/work/src/a.py",
                    "start": {"line": 4},
                    "end": {"line": 5},
                    "extra": {"severity": "INFO", "message": "snake_case"},
                }
            ]
        }
    )
    [f] = parse_semgrep(out, tmp_path)
    assert (f.file, f.line, f.end_line, f.severity, f.message) == (
        "src/a.py",
        4,
        5,
        "low",
        "snake_case",
    )
