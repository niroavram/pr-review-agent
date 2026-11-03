from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from pr_agent.models import Finding, FixProposal, Level, Verification
from pr_agent.nodes.gate import policy_gate
from pr_agent.policy.config import TEMPLATE, parse_config
from pr_agent.state import ReviewState

CFG = parse_config(TEMPLATE.read_text()).model_dump()
PATCH = "--- a/{0}\n+++ b/{0}\n@@ -1 +1 @@\n-x\n+y\n"


def _finding(fid: str, file: str) -> Finding:
    return Finding(id=fid, source="bandit", category="security", file=file, message="sqli")


def _fix(fid: str, file: str, verdict: str = "accept") -> FixProposal:
    return FixProposal(
        finding_id=fid,
        patch=PATCH.format(file),
        fix_type="security",
        critic_verdict=verdict,  # type: ignore[arg-type]
    )


def _state(**extra: Any) -> ReviewState:
    state: dict[str, Any] = {
        "config": CFG,
        "final_findings": [_finding("F1", "src/store/orders.py")],
        "fixes": [_fix("F1", "src/store/orders.py")],
        "verifications": [Verification(finding_id="F1", passed=True)],
    }
    return {**state, **extra}  # type: ignore[typeddict-item]


EMPTY: RunnableConfig = {"configurable": {}}


def test_no_candidates_no_interrupt() -> None:
    # outside a graph, interrupt() would raise, so returning proves we did not call it
    out = policy_gate(_state(verifications=[]), EMPTY)
    assert out["approved"] == [] and out["decisions"][0].level is Level.COMMENT


def test_hard_rule_patch_is_forbidden_and_not_a_candidate() -> None:
    skip = "--- a/tests/t.py\n+++ b/tests/t.py\n@@ -1 +1,2 @@\n+@pytest.mark.skip\n def test_x():\n"
    fix = FixProposal(finding_id="F1", patch=skip, fix_type="security", critic_verdict="accept")
    out = policy_gate(_state(fixes=[fix]), EMPTY)  # would raise if it tried to interrupt
    [d] = out["decisions"]
    assert d.level is Level.FORBIDDEN and d.decided_by == "hard_rule:no_test_skip"
    assert out["approved"] == []


def test_rejected_fix_is_not_a_proposal() -> None:
    out = policy_gate(_state(fixes=[_fix("F1", "src/store/orders.py", "reject")]), EMPTY)
    assert out["decisions"][0].level is Level.COMMENT and out["approved"] == []


def test_preset_approvals_filtered_to_candidates() -> None:
    out = policy_gate(_state(approved=["F1", "F9"]), EMPTY)
    assert out["approved"] == ["F1"] and out["decisions"][0].level is Level.SUGGEST


def test_interrupt_and_resume() -> None:
    builder = StateGraph(ReviewState)
    builder.add_node("gate", policy_gate)
    builder.add_edge(START, "gate")
    builder.add_edge("gate", END)
    graph = builder.compile(checkpointer=InMemorySaver())
    config: RunnableConfig = {"configurable": {"thread_id": "t1"}}

    first = graph.invoke(_state(), config)
    [intr] = first["__interrupt__"]
    assert intr.value == {
        "suggest": [{"id": "F1", "file": "src/store/orders.py", "message": "sqli"}]
    }

    final = graph.invoke(Command(resume=["F1", "F2"]), config)
    assert final["approved"] == ["F1"]
    assert final["decisions"][0].decided_by == "default_sensitivity -> medium"
