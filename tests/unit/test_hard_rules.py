import difflib

import pytest

from pr_agent.policy.hard_rules import hard_rule_violations


def udiff(path: str, before: str, after: str) -> str:
    """Real unified diff of one file (empty side = added/deleted file)."""
    src = f"a/{path}" if before else "/dev/null"
    dst = f"b/{path}" if after else "/dev/null"
    lines = difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True), src, dst
    )
    return "".join(lines)


def rules(patch: str) -> list[str]:
    return [name for name, _ in hard_rule_violations(patch)]


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (".pr-agent.yml", ["no_policy_edit"]),
        ("CONVENTIONS.md", ["no_policy_edit"]),
        ("ruff.toml", ["no_lint_config_edit"]),
        (".flake8", ["no_lint_config_edit"]),
        (".semgrep/rules.yml", ["no_lint_config_edit"]),
        ("pyproject.toml", ["no_lint_config_edit", "no_dependency_change"]),
        ("CODEOWNERS", ["no_codeowners_edit"]),
        ("docs/CODEOWNERS", ["no_codeowners_edit"]),
        (".github/CODEOWNERS", ["no_codeowners_edit", "no_ci_edit"]),
        (".github/workflows/ci.yml", ["no_ci_edit"]),
        (".gitlab-ci.yml", ["no_ci_edit"]),
        ("Jenkinsfile", ["no_ci_edit"]),
        ("requirements-dev.txt", ["no_dependency_change"]),
        ("uv.lock", ["no_dependency_change"]),
        ("Pipfile.lock", ["no_dependency_change"]),
        ("setup.py", ["no_dependency_change"]),
        ("../outside.py", ["path_escape"]),
    ],
)
def test_path_rules(path: str, expected: list[str]) -> None:
    assert rules(udiff(path, "a = 1\n", "a = 2\n")) == expected


def test_absolute_path_escapes() -> None:
    patch = "--- /etc/passwd\n+++ /etc/passwd\n@@ -1 +1 @@\n-x\n+y\n"
    assert rules(patch) == ["path_escape"]


TEST = "def test_a():\n    assert 1\n\n\ndef test_b():\n    assert 2\n"


def test_deleted_test_file() -> None:
    assert "no_test_deletion" in rules(udiff("tests/test_x.py", TEST, ""))
    assert "no_test_deletion" in rules(udiff("src/test_y.py", TEST, ""))


def test_removed_test_function() -> None:
    patch = udiff("tests/test_x.py", TEST, "def test_a():\n    assert 1\n")
    assert hard_rule_violations(patch) == [("no_test_deletion", "removed test_b")]


def test_edited_test_signature_is_not_a_deletion() -> None:
    patch = udiff("tests/test_x.py", TEST, TEST.replace("def test_b():", "def test_b(tmp_path):"))
    assert rules(patch) == []


@pytest.mark.parametrize(
    "marker",
    [
        "@pytest.mark.skip",
        '@pytest.mark.skipif(True, reason="x")',
        "@pytest.mark.xfail",
        "    pytest.skip('later')",
        "@unittest.skip('x')",
    ],
)
def test_skip_markers(marker: str) -> None:
    after = TEST.replace("def test_b", f"{marker}\ndef test_b")
    assert rules(udiff("tests/test_x.py", TEST, after)) == ["no_test_skip"]


def test_clean_patch_has_no_violations() -> None:
    assert rules(udiff("src/app.py", "import os\nx = 1\n", "x = 1\n")) == []
    assert rules(udiff("tests/test_x.py", TEST, TEST + "\n\ndef test_c():\n    pass\n")) == []


def test_malformed_patch_fails_closed() -> None:
    assert rules("--- a/x\n+++ b/x\n@@ -1,3 +1,3 @@\n a\n") == ["malformed_patch"]
    assert rules("not a diff\n") == ["malformed_patch"]
    assert rules("") == []
