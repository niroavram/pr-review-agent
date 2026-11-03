import pytest

from pr_agent.policy.api_diff import public_api_changes, signature

BASE = """
def charge(amount: int, currency: str = "EUR", *, retries: int = 3) -> int:
    return amount


def _helper(x):
    return x


class Client:
    def send(self, payload: dict) -> None:
        pass

    def _retry(self, n):
        pass


class _Internal:
    def run(self, a):
        pass
"""


def _changes(old: str, new: str) -> list[str]:
    return public_api_changes(BASE, BASE.replace(old, new))


def test_signature_format() -> None:
    import ast

    fn = ast.parse("def f(a, /, b, c=1, *args, d, e=2, **kw) -> int: pass").body[0]
    assert isinstance(fn, ast.FunctionDef)
    assert signature(fn) == "f(a, /, b, c=..., *args, d, e=..., **kw) -> int"


def test_unchanged_is_empty() -> None:
    assert public_api_changes(BASE, BASE) == []


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("amount: int, ", "amount: int, extra: int, "),  # arg added
        ("amount: int, ", ""),  # arg removed
        ("amount: int", "cents: int"),  # arg renamed
        ('currency: str = "EUR"', "currency: str"),  # default removed
        ("*, retries: int = 3", "retries: int = 3"),  # kw-only -> positional
        (") -> int:", ") -> str:"),  # return annotation
        ("def send(self, payload: dict)", "def send(self, payload: dict, *rest)"),  # varargs
    ],
)
def test_public_signature_changes(old: str, new: str) -> None:
    [change] = _changes(old, new)
    assert change.startswith("changed ")


def test_default_value_change_is_not_a_signature_change() -> None:
    assert _changes('"EUR"', '"USD"') == []


def test_removals() -> None:
    assert _changes("def charge(", "def _charge(") == ["removed charge"]
    assert _changes("class Client:", "class _Client:") == ["removed Client", "removed Client.send"]


def test_private_changes_ignored() -> None:
    assert _changes("def _helper(x)", "def _helper(x, y)") == []
    assert _changes("def _retry(self, n)", "def _retry(self)") == []
    assert _changes("def run(self, a)", "def run(self)") == []  # method of a private class


def test_additions_not_counted() -> None:
    assert public_api_changes(BASE, BASE + "\n\ndef refund(x):\n    pass\n") == []
    assert _changes("    def _retry", "    def extra(self):\n        pass\n\n    def _retry") == []


def test_syntax_error_fails_closed() -> None:
    [change] = public_api_changes(BASE, "def broken(:\n")
    assert "cannot parse" in change
