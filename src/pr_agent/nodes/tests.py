"""Test runner node: report tests this PR breaks (fail on head, pass on base).

Running a PR's tests executes its code, so this only happens in an isolated sandbox or for
--local reviews (the user's own code). Failures that also fail on base are pre-existing:
noted in tool_status, never reported as findings. A test finding is explain-only
(fixable=False): the easiest "fix" for a failing test is to weaken the test.
"""

from __future__ import annotations

import ast
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from langchain_core.runnables import RunnableConfig

from pr_agent.deps import get_deps
from pr_agent.gitutil import materialize
from pr_agent.models import Finding
from pr_agent.sandbox import Sandbox
from pr_agent.state import ReviewState

PYTEST_ARGS = ["-m", "pytest", "-q", "-p", "no:cacheprovider", "-rfE"]
# Short test summary lines: "FAILED tests/test_x.py::test_y - AssertionError: assert 1 == 2"
_SUMMARY = re.compile(r"^(?:FAILED|ERROR) (\S+)(?: - (.*))?$")
NO_TESTS_COLLECTED = 5
NOT_FOUND = 4  # pytest usage error, e.g. "not found: tests/x.py::test_new"
MAX_RERUNS = 20  # each re-run on base is a pytest start-up; cap the cost
MESSAGE_LIMIT = 200
SKIPPED_BANNER = "⚠️ Tests: not run. The sandbox is not isolated and this PR's code is untrusted."


@dataclass
class Failure:
    nodeid: str  # "tests/test_x.py::TestC::test_y[param]"
    reason: str  # first line of pytest's short summary reason


def parse_failures(output: str) -> list[Failure]:
    """FAILED/ERROR lines from pytest's -rfE short summary, deduplicated in order."""
    seen: dict[str, Failure] = {}
    for line in output.splitlines():
        if (m := _SUMMARY.match(line.strip())) and m.group(1) not in seen:
            seen[m.group(1)] = Failure(m.group(1), (m.group(2) or "").strip())
    return list(seen.values())


def run_pytest(
    sandbox: Sandbox, workdir: Path, nodeids: list[str], timeout: int
) -> tuple[int, list[Failure], bool]:
    """pytest in workdir (all tests, or just nodeids). Returns (exit code, failures, timed out)."""
    res = sandbox.run([*sandbox.python(), *PYTEST_ARGS, *nodeids], workdir, timeout=timeout)
    return res.returncode, parse_failures(res.stdout), res.timed_out


def passes_on_base(sandbox: Sandbox, base_dir: Path, nodeid: str, timeout: int) -> bool:
    """True if the test passes on base, or does not exist there (the PR added it failing)."""
    code, _, timed_out = run_pytest(sandbox, base_dir, [nodeid], timeout)
    return not timed_out and code in (0, NOT_FOUND, NO_TESTS_COLLECTED)


def def_line(workdir: Path, nodeid: str) -> int:
    """Line of the test's `def` in the head file (via ast), else 1."""
    file, *names = nodeid.split("::")
    if not names:
        return 1
    *classes, func = [n.split("[", 1)[0] for n in names]  # drop the parametrize id
    try:
        tree = ast.parse((workdir / file).read_text())
    except (OSError, SyntaxError, ValueError):
        return 1
    body: list[ast.stmt] = tree.body
    for cls in classes:
        node = next((n for n in body if isinstance(n, ast.ClassDef) and n.name == cls), None)
        if node is None:
            return 1
        body = node.body
    funcs = (ast.FunctionDef, ast.AsyncFunctionDef)
    return next((n.lineno for n in body if isinstance(n, funcs) and n.name == func), 1)


def introduced_finding(workdir: Path, failure: Failure, new: bool) -> Finding:
    """An explain-only finding for a test this PR breaks."""
    where = "is new in this PR and fails" if new else "fails on this PR but passes on base"
    reason = failure.reason[:MESSAGE_LIMIT] or "see the test log"
    return Finding(
        source="pytest",
        rule_id="pytest:failed",
        category="test",
        severity="high",
        file=failure.nodeid.split("::", 1)[0],
        line=def_line(workdir, failure.nodeid),
        message=f"{failure.nodeid} {where}: {reason}",
        fixable=False,
    )


def classify(
    sandbox: Sandbox, workdir: Path, base_dir: Path, failures: list[Failure], timeout: int
) -> tuple[list[Finding], list[str]]:
    """Split head failures into introduced findings and pre-existing node ids."""
    findings: list[Finding] = []
    pre_existing: list[str] = []
    for failure in failures[:MAX_RERUNS]:
        file = failure.nodeid.split("::", 1)[0]
        new = not (base_dir / file).exists()
        if new or passes_on_base(sandbox, base_dir, failure.nodeid, timeout):
            findings.append(introduced_finding(workdir, failure, new))
        else:
            pre_existing.append(failure.nodeid)
    return findings, pre_existing


def status_text(failures: int, introduced: int, pre_existing: list[str]) -> str:
    """One-line pytest summary for tool_status."""
    if not failures:
        return "ok"
    text = f"ok: {failures} failing, {introduced} introduced by this PR"
    if pre_existing:
        text += f", pre-existing: {', '.join(pre_existing[:5])}"
    if failures > MAX_RERUNS:
        text += f" (only the first {MAX_RERUNS} were checked against base)"
    return text


def test_runner(state: ReviewState, config: RunnableConfig) -> dict:
    """Graph node: run pytest on head, re-run failures on base, report introduced failures."""
    deps = get_deps(config)
    ctx = state["ctx"]
    if not (deps.sandbox.isolated or ctx.mode == "local"):
        return {
            "tool_status": {"pytest": "skipped: unsandboxed remote code"},
            "banners": [SKIPPED_BANNER],
        }
    timeout = deps.settings.test_timeout
    workdir = materialize(ctx.repo_path, ctx.head_sha)
    base_dir = materialize(ctx.repo_path, ctx.base_sha)
    try:
        code, failures, timed_out = run_pytest(deps.sandbox, workdir, [], timeout)
        if timed_out:
            return {"tool_status": {"pytest": f"error: timed out after {timeout}s"}}
        if code == NO_TESTS_COLLECTED:
            return {"tool_status": {"pytest": "ok: no tests collected"}}
        if code != 0 and not failures:
            return {"tool_status": {"pytest": f"error: pytest exit {code}"}}
        findings, pre_existing = classify(deps.sandbox, workdir, base_dir, failures, timeout)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        shutil.rmtree(base_dir, ignore_errors=True)
    status = status_text(len(failures), len(findings), pre_existing)
    return {"findings": findings, "tool_status": {"pytest": status}}


# The name starts with "test_": stop pytest from collecting it wherever it is imported.
test_runner.__test__ = False  # type: ignore[attr-defined]
