import sys
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pr_agent.agents.critic import CriticOutput
from pr_agent.agents.fixer import Edit, FixOutput
from pr_agent.agents.reviewers import LLMFinding, ReviewOutput
from pr_agent.deps import Deps
from pr_agent.gitutil import rev_parse
from pr_agent.models import ChangedFile, Finding, FixProposal, PRContext
from pr_agent.nodes.fix import (
    FixState,
    boundaries_text,
    critic,
    done,
    propose,
    route_after_critic,
    route_after_propose,
)
from pr_agent.nodes.review import make_reviewer_node
from pr_agent.settings import Settings
from pr_agent.state import ReviewState
from tests.fakes import FakeLLM, FakeSandbox

ORDERS = "src/store/orders.py"


def cfg(llm: Any) -> Any:
    return {"configurable": {"deps": Deps(llm=llm)}}


@pytest.fixture
def ctx(demo_repo: Path) -> PRContext:
    return PRContext(
        repo_path=str(demo_repo),
        repo_name="demo",
        pr_id="case/01-sql-injection",
        base_sha=rev_parse(demo_repo, "main"),
        head_sha=rev_parse(demo_repo, "case/01-sql-injection"),
        files=[ChangedFile(path=ORDERS)],
    )


@pytest.mark.parametrize(
    ("verdict", "attempts", "expected"),
    [
        ("accept", 1, "verify"),
        ("revise", 1, "propose"),
        ("revise", Settings().max_revisions, "propose"),
        ("revise", Settings().max_revisions + 1, "done"),
        ("reject", 1, "done"),
    ],
)
def test_route_after_critic(verdict: str, attempts: int, expected: str) -> None:
    assert route_after_critic({"verdict": verdict, "attempts": attempts}) == expected


def test_revise_loop_increments_attempts_then_records_reject(ctx: PRContext) -> None:
    edit = Edit(file=ORDERS, old="'{customer}'", new="?")
    llm = FakeLLM(
        {
            "FixOutput": FixOutput(edits=[edit], explanation="e"),
            "CriticOutput": CriticOutput(verdict="revise", notes="also pass params"),
        }
    )
    finding = Finding(id="F1", source="bandit", category="security", file=ORDERS, message="x")
    state: FixState = {"finding": finding, "ctx": ctx, "config": None, "attempts": 0}
    config = cfg(llm)
    route = "propose"
    while route == "propose":
        state.update(propose(state, config))  # type: ignore[typeddict-item]
        state.update(critic(state, config))  # type: ignore[typeddict-item]
        route = route_after_critic(state)
    assert route == "done" and state["attempts"] == Settings().max_revisions + 1
    assert "also pass params" in llm.calls[-2]["user"]  # feedback reached the fixer
    [rejected] = done(state, config)["fixes"]
    assert rejected.critic_verdict == "reject" and rejected.attempts == state["attempts"]


def test_propose_without_patch_rejects(ctx: PRContext) -> None:
    finding = Finding(id="F1", source="bandit", category="security", file=ORDERS, message="x")
    out = propose({"finding": finding, "ctx": ctx}, cfg(FakeLLM()))
    assert out == {
        "proposal": None,
        "verdict": "reject",
        "feedback": "could not build patch",
        "attempts": 1,
    }
    assert done({"proposal": None}, cfg(FakeLLM())) == {}


def test_critic_stores_verdict_on_copy(ctx: PRContext) -> None:
    proposal = FixProposal(finding_id="F1", patch="p", fix_type="bug")
    finding = Finding(id="F1", source="llm:bug", category="bug", file=ORDERS, message="x")
    llm = FakeLLM({"CriticOutput": CriticOutput(verdict="accept", notes="ok")})
    out = critic({"finding": finding, "ctx": ctx, "proposal": proposal}, cfg(llm))
    assert out["verdict"] == "accept" and out["proposal"].critic_notes == "ok"
    assert proposal.critic_verdict is None


def test_boundaries_text() -> None:
    assert "fail closed" in boundaries_text(None)
    text = boundaries_text({"levels": {"low": "auto"}, "limits": {"auto_max_lines": 20}})
    assert "low=auto" in text and "20 lines" in text


def test_reviewer_node_skips_kind_excluded_by_triage(ctx: PRContext) -> None:
    llm = FakeLLM(
        {"ReviewOutput": ReviewOutput(findings=[LLMFinding(file=ORDERS, line=1, message="x")])}
    )
    state: ReviewState = {"ctx": ctx, "triage": {"reviewers": ["security"]}}
    assert make_reviewer_node("bug")(state, cfg(llm)) == {"findings": []}
    assert llm.calls == []
    assert len(make_reviewer_node("security")(state, cfg(llm))["findings"]) == 1


def test_reviewer_node_never_raises(ctx: PRContext) -> None:
    def boom(system: str, user: str) -> Any:
        raise RuntimeError("api down")

    out = make_reviewer_node("security")({"ctx": ctx}, cfg(FakeLLM({"ReviewOutput": boom})))
    assert out == {"findings": [], "tool_status": {"llm:security": "error: api down"}}


# --- Deterministic (tool) fixes -------------------------------------------------------------

RUFF_PATCH = "--- a/src/store/orders.py\n+++ b/src/store/orders.py\n@@ -1 +1 @@\n-x\n+y\n"


def fake_ruff(monkeypatch: pytest.MonkeyPatch, fn: Callable[..., str | None]) -> list[Any]:
    """Install a stand-in `pr_agent.analyzers.ruff` module; returns the recorded calls."""
    calls: list[Any] = []

    def ruff_fix_patch(ctx: PRContext, finding: Finding, sandbox: Any) -> str | None:
        calls.append((ctx, finding, sandbox))
        return fn(ctx, finding, sandbox)

    module = types.ModuleType("pr_agent.analyzers.ruff")
    module.ruff_fix_patch = ruff_fix_patch  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pr_agent.analyzers.ruff", module)
    return calls


def ruff_finding() -> Finding:
    return Finding(
        id="F2", source="ruff", rule_id="ruff:F401", category="lint", file=ORDERS, message="unused"
    )


def test_ruff_finding_gets_deterministic_fix_without_llm(
    ctx: PRContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = fake_ruff(monkeypatch, lambda *_: RUFF_PATCH)
    llm = FakeLLM()
    sandbox = FakeSandbox()
    config = {"configurable": {"deps": Deps(llm=llm, sandbox=sandbox)}}
    state: FixState = {"finding": ruff_finding(), "ctx": ctx, "attempts": 0}
    out = propose(state, config)
    proposal = out["proposal"]
    assert (proposal.author, proposal.fix_type, proposal.patch) == (
        "deterministic",
        "lint",
        RUFF_PATCH,
    )
    assert (proposal.critic_verdict, proposal.critic_notes) == ("accept", "deterministic tool fix")
    assert proposal.finding_id == "F2" and out["attempts"] == 1
    assert calls[0][2] is sandbox
    assert route_after_propose(out) == "verify"
    # Even if wired through the critic, a tool fix never reaches the LLM.
    assert critic({**state, **out}, config) == {"verdict": "accept"}  # type: ignore[typeddict-item]
    assert llm.calls == []


@pytest.mark.parametrize("behaviour", ["none", "raises"])
def test_ruff_without_tool_fix_falls_back_to_llm(
    ctx: PRContext, monkeypatch: pytest.MonkeyPatch, behaviour: str
) -> None:
    def tool(*_: Any) -> str | None:
        if behaviour == "raises":
            raise RuntimeError("ruff crashed")
        return None

    fake_ruff(monkeypatch, tool)
    edit = Edit(file=ORDERS, old="'{customer}'", new="?")
    llm = FakeLLM({"FixOutput": FixOutput(edits=[edit], explanation="e")})
    out = propose({"finding": ruff_finding(), "ctx": ctx}, cfg(llm))
    assert out["proposal"].author == "llm" and llm.calls[0]["role"] == "fix"
    assert route_after_propose(out) == "critic"


def test_non_ruff_findings_never_call_the_tool(
    ctx: PRContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = fake_ruff(monkeypatch, lambda *_: RUFF_PATCH)
    finding = Finding(id="F1", source="bandit", category="security", file=ORDERS, message="x")
    out = propose({"finding": finding, "ctx": ctx}, cfg(FakeLLM()))
    assert calls == [] and out["proposal"] is None


def test_route_after_propose() -> None:
    llm_fix = FixProposal(finding_id="F1", patch="p", fix_type="bug")
    tool_fix = llm_fix.model_copy(update={"author": "deterministic"})
    assert route_after_propose({"proposal": None}) == "done"
    assert route_after_propose({}) == "done"
    assert route_after_propose({"proposal": llm_fix}) == "critic"
    assert route_after_propose({"proposal": tool_fix}) == "verify"
