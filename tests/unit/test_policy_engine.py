import pytest

from pr_agent.models import Finding, FixProposal, Level, Verification
from pr_agent.policy.config import TEMPLATE, AutonomyConfig, parse_config
from pr_agent.policy.engine import decide, patch_paths, path_level, pre_ceiling


@pytest.fixture(scope="module")
def cfg() -> AutonomyConfig:
    return parse_config(TEMPLATE.read_text())


def _diff(*paths: str) -> str:
    return "".join(f"--- a/{p}\n+++ b/{p}\n@@ -1 +1 @@\n-x\n+y\n" for p in paths)


def _finding(file: str, source: str = "bandit", category: str = "security") -> Finding:
    return Finding(id="F1", source=source, category=category, file=file, message="m")  # type: ignore[arg-type]


def _proposal(*paths: str) -> FixProposal:
    return FixProposal(finding_id="F1", patch=_diff(*paths), fix_type="security")


OK = Verification(finding_id="F1", passed=True)
FAILED = Verification(finding_id="F1", passed=False, checks={"tests_pass": False})


def test_patch_paths() -> None:
    assert patch_paths(_diff("src/a.py", "tests/b.py")) == ["src/a.py", "tests/b.py"]
    new_file = "--- /dev/null\n+++ b/new.py\n@@ -0,0 +1 @@\n+x\n"
    assert patch_paths(new_file) == ["new.py"]
    assert patch_paths("--- a/x\n+++ b/x\n@@ -1,3 +1,3 @@\n a\n") == []  # malformed


PAY = ["@payments-team"]


@pytest.mark.parametrize(
    ("path", "level", "decided_by", "owners"),
    [
        ("src/payments/x.py", Level.FORBIDDEN, 'paths[0] "src/payments/**" -> critical', PAY),
        ("lib/crypto/aes.py", Level.FORBIDDEN, 'paths[0] "**/crypto/**" -> critical', PAY),
        ("tests/x.py", Level.AUTO, 'paths[3] "tests/**" -> low', []),
        ("src/store/orders.py", Level.SUGGEST, "default_sensitivity -> medium", []),
        ("migrations/001.sql", Level.COMMENT, 'paths[1] "migrations/**" -> high', ["@platform"]),
    ],
)
def test_path_level(
    cfg: AutonomyConfig, path: str, level: Level, decided_by: str, owners: list[str]
) -> None:
    assert path_level(path, cfg) == (level, decided_by, owners)


def test_overlapping_rules_most_restrictive_and_owners_unioned(cfg: AutonomyConfig) -> None:
    data = cfg.model_dump()
    data["paths"].append({"match": ["src/payments/**"], "sensitivity": "low", "owners": ["@x"]})
    level, by, owners = path_level("src/payments/x.py", AutonomyConfig.model_validate(data))
    assert level is Level.FORBIDDEN and by.startswith("paths[0]")
    assert owners == ["@payments-team", "@x"]


def test_most_restrictive_path_in_patch_wins(cfg: AutonomyConfig) -> None:
    d = decide(_finding("tests/x.py"), _proposal("tests/x.py", "src/auth/t.py"), OK, cfg)
    assert d.level is Level.FORBIDDEN and d.owners == ["@payments-team"]
    assert d.decided_by == 'paths[0] "src/auth/**" -> critical'


def test_fix_type_cap(cfg: AutonomyConfig) -> None:
    lint = decide(_finding("tests/x.py", "ruff", "lint"), _proposal("tests/x.py"), OK, cfg)
    assert lint.level is Level.AUTO and lint.decided_by == 'paths[3] "tests/**" -> low'
    sec = decide(_finding("tests/x.py"), _proposal("tests/x.py"), OK, cfg)
    assert sec.level is Level.SUGGEST and sec.decided_by == "fix_types.security -> suggest"


def test_tie_reports_first_constraint(cfg: AutonomyConfig) -> None:
    d = decide(_finding("src/store/orders.py"), _proposal("src/store/orders.py"), OK, cfg)
    assert d.level is Level.SUGGEST and d.decided_by == "default_sensitivity -> medium"


def test_fail_closed(cfg: AutonomyConfig) -> None:
    d = decide(_finding("tests/x.py", "ruff", "lint"), _proposal("tests/x.py"), OK, None)
    assert d.level is Level.SUGGEST and d.decided_by == "fail_closed: no valid base config"
    assert decide(_finding("tests/x.py"), None, None, None).level is Level.COMMENT
    assert pre_ceiling(_finding("tests/x.py"), None) is Level.SUGGEST


def test_no_proposal_comments(cfg: AutonomyConfig) -> None:
    d = decide(_finding("tests/x.py"), None, None, cfg)
    assert d.level is Level.COMMENT and d.decided_by == "no verified patch"


def test_failed_verification_comments(cfg: AutonomyConfig) -> None:
    d = decide(_finding("tests/x.py"), _proposal("tests/x.py"), FAILED, cfg)
    assert d.level is Level.COMMENT and "verification" in d.reason


def test_unfixable_comments(cfg: AutonomyConfig) -> None:
    f = _finding("tests/x.py").model_copy(update={"fixable": False})
    assert decide(f, _proposal("tests/x.py"), OK, cfg).level is Level.COMMENT


def test_forbidden_location_reports_owners_without_patch(cfg: AutonomyConfig) -> None:
    d = decide(_finding("src/payments/charges.py"), None, None, cfg)
    assert d.level is Level.FORBIDDEN and d.owners == ["@payments-team"]
    assert pre_ceiling(_finding("src/payments/charges.py"), cfg) is Level.FORBIDDEN
