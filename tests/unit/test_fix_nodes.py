from pathlib import Path
from typing import Any

import pytest

from pr_agent.agents.critic import CriticOutput
from pr_agent.agents.fixer import Edit, FixOutput
from pr_agent.agents.reviewers import LLMFinding, ReviewOutput
from pr_agent.deps import Deps
from pr_agent.gitutil import rev_parse
from pr_agent.models import ChangedFile, Finding, FixProposal, PRContext
from pr_agent.nodes.fix import FixState, boundaries_text, critic, done, propose, route_after_critic
from pr_agent.nodes.review import make_reviewer_node
from pr_agent.settings import Settings
from pr_agent.state import ReviewState
from tests.fakes import FakeLLM

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
