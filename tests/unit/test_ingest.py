from pathlib import Path

from pr_agent.deps import Deps
from pr_agent.gitutil import git, rev_parse
from pr_agent.ingest.local import load_local
from pr_agent.models import PRContext
from pr_agent.nodes.ingest import ingest
from tests.fakes import FakeLLM

BRANCH = "case/01-sql-injection"


def _config() -> dict:
    return {"configurable": {"deps": Deps(llm=FakeLLM())}}


def _commit(repo: Path, msg: str) -> None:
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", msg)


def test_load_local_case_branch(demo_repo: Path) -> None:
    ctx = load_local(demo_repo, base="main", head=BRANCH)
    files = {f.path: f for f in ctx.files}
    assert "src/store/orders.py" in files and 20 in files["src/store/orders.py"].added_lines
    assert ctx.title == "Add order search by customer"
    assert "find_orders_by_customer" in ctx.description
    assert ctx.pr_id == "case-01-sql-injection" and ctx.head_ref == BRANCH
    assert ctx.base_sha == rev_parse(demo_repo, "main")
    assert ctx.head_sha == rev_parse(demo_repo, BRANCH)
    assert ctx.repo_name == demo_repo.name and ctx.mode == "local"


def test_load_local_sha_head_uses_short_sha(demo_repo: Path) -> None:
    sha = rev_parse(demo_repo, BRANCH)
    assert load_local(demo_repo, head=sha).pr_id == sha[:8]


def test_ingest_node_loads_base_config_and_conventions(demo_repo: Path) -> None:
    ctx = load_local(demo_repo, head=BRANCH)
    out = ingest({"ctx": ctx}, _config())  # type: ignore[arg-type]
    assert out["config"] is not None and out["config_error"] is None
    assert "CONV-004" in out["conventions"]
    assert out["banners"] == [] and "findings" not in out


def test_ingest_fails_closed_and_flags_config_change(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "a.py").write_text("x = 1\n")
    _commit(tmp_path, "init")
    git(tmp_path, "checkout", "-q", "-b", "feature")
    (tmp_path / ".pr-agent.yml").write_text("version: 1\n")
    _commit(tmp_path, "Add config")
    ctx: PRContext = load_local(tmp_path, head="feature")
    out = ingest({"ctx": ctx}, _config())  # type: ignore[arg-type]
    assert out["config"] is None and "not found" in out["config_error"]
    assert out["conventions"] == ""
    assert len(out["banners"]) == 1 and "Failing closed" in out["banners"][0]
    (finding,) = out["findings"]
    assert finding.file == ".pr-agent.yml" and finding.category == "config"
    assert not finding.fixable
