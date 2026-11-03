from typing import Any

import pytest

from pr_agent.models import ChangedFile, PRContext
from pr_agent.nodes.triage import ALL_REVIEWERS, MAX_DIFF_LINES, triage


def run(paths: list[str], *, deleted: tuple[str, ...] = (), diff: str = "") -> dict[str, Any]:
    """Triage a PR touching `paths` (those in `deleted` are deletions)."""
    files = [ChangedFile(path=p, status="deleted" if p in deleted else "modified") for p in paths]
    ctx = PRContext(
        repo_path=".", repo_name="r", pr_id="1", base_sha="a", head_sha="b", files=files, diff=diff
    )
    out: dict[str, Any] = triage({"ctx": ctx}, {})["triage"]
    return out


def test_python_pr_runs_all_reviewers() -> None:
    out = run(["src/app.py", "README.md"])
    assert out["reviewers"] == ALL_REVIEWERS
    assert out["python_files"] == ["src/app.py"]
    assert out["skipped_files"] == [] and out["notes"] == []


@pytest.mark.parametrize(
    ("paths", "note"),
    [
        (["README.md", "docs/guide/setup.html"], "Docs-only PR"),
        (["pyproject.toml", ".github/workflows/ci.yml"], "Config-only PR"),
        (["CHANGELOG.md", "settings.yaml"], "Docs/config-only PR"),
        (["web/app.js"], "No Python changes"),
    ],
)
def test_prs_without_python_skip_llm_reviewers(paths: list[str], note: str) -> None:
    out = run(paths)
    assert out["reviewers"] == [] and out["python_files"] == []
    assert out["notes"][0].startswith(note)


def test_skipped_files_use_is_reviewable() -> None:
    out = run(["src/app.py", "uv.lock", "logo.png", "vendor/lib.py", "api_pb2.py"])
    assert out["skipped_files"] == ["uv.lock", "logo.png", "vendor/lib.py", "api_pb2.py"]
    assert out["python_files"] == ["src/app.py"]  # vendored/generated Python is not reviewed
    assert any("4 non-reviewable" in n for n in out["notes"])


def test_only_generated_python_means_no_reviewers() -> None:
    out = run(["api_pb2.py", "poetry.lock"])
    assert out["reviewers"] == [] and out["python_files"] == []


def test_deleted_python_is_not_reviewed() -> None:
    out = run(["src/old.py"], deleted=("src/old.py",))
    assert out["reviewers"] == [] and out["python_files"] == []


def test_huge_diff_runs_only_security() -> None:
    out = run(["src/app.py"], diff="\n" * (MAX_DIFF_LINES + 1))
    assert out["reviewers"] == ["security"]
    assert f"Diff over {MAX_DIFF_LINES} lines" in out["notes"][0]


def test_huge_docs_diff_still_runs_no_reviewers() -> None:
    assert run(["README.md"], diff="\n" * (MAX_DIFF_LINES + 1))["reviewers"] == []
