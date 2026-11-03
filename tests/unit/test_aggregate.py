from typing import Any

from pr_agent.deps import Deps
from pr_agent.models import Finding
from pr_agent.nodes.aggregate import aggregate
from pr_agent.settings import Settings
from tests.fakes import FakeLLM

CONVENTIONS = "## CONV-004: Parameterized SQL only\n## CONV-012: No print in library code\n"


def run(findings: list[Finding], **settings: Any) -> list[Finding]:
    """Aggregate with min_confidence 0.6 and max_comments 15 unless overridden."""
    s = Settings(**{"min_confidence": 0.6, "max_comments": 15, **settings})
    config = {"configurable": {"deps": Deps(llm=FakeLLM(), settings=s)}}
    state = {"findings": findings, "conventions": CONVENTIONS}
    out: list[Finding] = aggregate(state, config)["final_findings"]  # type: ignore[arg-type]
    return out


def llm(line: int = 10, **kw: Any) -> Finding:
    """An LLM security finding in a.py (override any field)."""
    base: dict[str, Any] = {
        "source": "llm:security",
        "category": "security",
        "file": "a.py",
        "line": line,
        "message": "m",
        "confidence": 0.9,
    }
    return Finding(**{**base, **kw})


def tool(line: int = 10, **kw: Any) -> Finding:
    """A bandit finding in a.py (override any field)."""
    base: dict[str, Any] = {
        "source": "bandit",
        "rule_id": "bandit:B608",
        "category": "security",
        "file": "a.py",
        "line": line,
        "message": "t",
    }
    return Finding(**{**base, **kw})


def test_clean_pr_gives_no_findings() -> None:
    assert run([]) == []


def test_low_confidence_llm_findings_are_dropped_but_tools_are_not_thresholded() -> None:
    out = run([llm(confidence=0.59), llm(line=50, confidence=0.6), tool(line=90, confidence=0.1)])
    assert [(f.source, f.line) for f in out] == [("llm:security", 50), ("bandit", 90)]


def test_convention_findings_must_cite_a_known_conv_id() -> None:
    conv = {"source": "llm:conventions", "category": "convention"}
    out = run(
        [
            llm(line=10, rule_id="conv:CONV-004", **conv),
            llm(line=30, rule_id="conv:CONV-999", **conv),  # unknown id
            llm(line=50, rule_id=None, **conv),  # no id at all
        ]
    )
    assert [f.rule_id for f in out] == ["conv:CONV-004"]


def test_dedupe_within_two_lines_prefers_tool_finding() -> None:
    out = run([llm(line=11, severity="critical", confidence=1.0), tool(line=10, severity="low")])
    assert [f.source for f in out] == ["bandit"]


def test_dedupe_treats_security_and_bug_as_one_kind_but_not_others() -> None:
    out = run(
        [
            tool(line=10),
            llm(line=12, category="bug", source="llm:bug"),  # dup of the security finding
            llm(line=13, source="llm:security"),  # 3 lines away: not a dup
            llm(line=10, file="b.py"),  # other file: not a dup
            llm(line=10, category="convention", source="llm:conventions", rule_id="conv:CONV-012"),
        ]
    )
    assert sorted((f.file, f.line, f.category) for f in out) == [
        ("a.py", 10, "convention"),
        ("a.py", 10, "security"),
        ("a.py", 13, "security"),
        ("b.py", 10, "security"),
    ]


def test_sorted_by_severity_then_location_and_numbered() -> None:
    out = run(
        [
            llm(line=40, severity="low"),
            llm(line=30, file="b.py", severity="critical"),
            llm(line=20, severity="high"),
            llm(line=10, file="c.py", severity="high"),
        ]
    )
    assert [(f.id, f.file, f.line) for f in out] == [
        ("F1", "b.py", 30),
        ("F2", "a.py", 20),
        ("F3", "c.py", 10),
        ("F4", "a.py", 40),
    ]


def test_capped_at_max_comments_keeping_most_severe() -> None:
    findings = [llm(line=i * 10, severity="low") for i in range(1, 6)]
    findings.append(llm(line=100, severity="critical"))
    out = run(findings, max_comments=3)
    assert [f.id for f in out] == ["F1", "F2", "F3"]
    assert out[0].severity == "critical" and out[0].line == 100


def test_input_findings_are_not_mutated() -> None:
    original = llm()
    [out] = run([original])
    assert out.id == "F1" and original.id == ""
