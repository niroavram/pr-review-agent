from pathlib import Path

import pytest

from pr_agent.gitutil import git, materialize, rev_parse, show_file
from pr_agent.models import Finding, Level
from pr_agent.policy.config import TEMPLATE, load_base_config, parse_config
from pr_agent.tracing import redact, redact_text

REPO = Path(__file__).resolve().parents[2]


def test_level_ordering_most_restrictive_wins() -> None:
    assert max(Level.AUTO, Level.FORBIDDEN, Level.SUGGEST) is Level.FORBIDDEN
    assert Level.parse("suggest") is Level.SUGGEST and Level.COMMENT.label == "comment"


def test_finding_defaults() -> None:
    f = Finding(source="bandit", category="security", file="a.py", message="x")
    assert f.confidence == 1.0 and f.fixable


def test_template_parses_and_demo_copy_is_identical() -> None:
    cfg = parse_config(TEMPLATE.read_text())
    assert cfg.levels["critical"] == "forbidden" and cfg.limits.auto_max_lines == 20
    assert (REPO / "demo/base/.pr-agent.yml").read_bytes() == TEMPLATE.read_bytes()


LEVELS = "levels: {low: auto, medium: suggest, high: comment, critical: forbidden}"


@pytest.mark.parametrize(
    "text",
    [
        f"version: 2\n{LEVELS}",
        "version: 1\nlevels: {low: auto}",
        f"version: 1\n{LEVELS}\nx: 1",
        "[: not yaml",
    ],
)
def test_invalid_configs_rejected(text: str) -> None:
    with pytest.raises(ValueError):
        parse_config(text)


def test_demo_build_creates_case_branch(demo_repo: Path) -> None:
    branches = git(demo_repo, "branch", "--format=%(refname:short)").split()
    assert "main" in branches and "case/01-sql-injection" in branches
    head = rev_parse(demo_repo, "case/01-sql-injection")
    assert "find_orders_by_customer" in (show_file(demo_repo, head, "src/store/orders.py") or "")
    assert "Add order search" in git(demo_repo, "log", "-1", "--format=%B", head)


def test_config_loaded_from_base(demo_repo: Path) -> None:
    cfg, err = load_base_config(demo_repo, rev_parse(demo_repo, "main"))
    assert cfg is not None and err is None


def test_missing_config_fails_closed(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "a.txt").write_text("x")
    git(tmp_path, "add", "-A")
    git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    cfg, err = load_base_config(tmp_path, rev_parse(tmp_path, "main"))
    assert cfg is None and err and "not found" in err


def test_materialize_exports_tree(demo_repo: Path) -> None:
    d = materialize(demo_repo, "main")
    assert (d / "src/store/orders.py").exists() and not (d / ".git").exists()


def test_redaction() -> None:
    from pr_agent.demo import demo_secret

    value = demo_secret("test")
    out = redact_text(f'api_key = "{value}"\nname = "{value}"')
    assert value not in out.splitlines()[0] and "[REDACTED]" in out
    assert redact({"a": [f'password="{value}"']}) == {"a": ['password="[REDACTED]"']}
    assert redact_text('password = "hello"') == 'password = "hello"'  # short/low-entropy kept
