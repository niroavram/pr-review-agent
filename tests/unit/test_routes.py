from pathlib import Path

import pytest

from pr_agent.models import Level
from pr_agent.policy.config import TEMPLATE, AutonomyConfig, parse_config
from pr_agent.policy.routes import Route, resolve_routes, route_level, touched_routes

DEMO_ROUTES = (Path(__file__).parents[2] / "demo/base/src/api/routes.py").read_text()

FLASK = """from flask import Flask

app = Flask(__name__)


@app.route("/orders", methods=["GET", "POST"])
def orders():
    return "ok"


@app.route("/health")
def health():
    return "ok"
"""

NON_LITERAL = """from fastapi import APIRouter

PREFIX = "/v1"
router = APIRouter(prefix=PREFIX)
other = APIRouter()
BASE = "/x"


@router.get("/a")
def a():
    pass


@other.post(BASE + "/b")
def b():
    pass


@imported_router.delete("/c")
def c():
    pass


@mock.patch("pkg.fn")
def not_a_route():
    pass
"""


@pytest.fixture(scope="module")
def cfg() -> AutonomyConfig:
    return parse_config(TEMPLATE.read_text())


def test_fastapi_prefix_joined_and_span_includes_decorator() -> None:
    routes = resolve_routes(DEMO_ROUTES)
    assert [(r.method, r.path, r.resolved) for r in routes] == [
        ("GET", "/v1/public/orders/{order_id}", True),
        ("POST", "/v1/payments/{order_id}/discount", True),
        ("GET", "/v1/admin/orders/{order_id}", True),
    ]
    lines = DEMO_ROUTES.splitlines()
    post = routes[1]
    assert lines[post.start_line - 1].startswith("@router.post")
    assert lines[post.end_line - 1].strip().startswith("return")


def test_flask_methods_default_get() -> None:
    routes = resolve_routes(FLASK)
    assert [(r.method, r.path) for r in routes] == [
        ("GET", "/orders"),
        ("POST", "/orders"),
        ("GET", "/health"),
    ]
    assert all(r.resolved for r in routes)


def test_non_literal_prefix_or_path_is_unresolved() -> None:
    routes = {r.start_line: r for r in resolve_routes(NON_LITERAL)}
    resolved = {(r.method, r.resolved) for r in routes.values()}
    # a: prefix is a variable; b: path is an expression; c: router imported (prefix unknown)
    assert resolved == {("GET", False), ("POST", False), ("DELETE", False)}
    assert len(routes) == 3  # mock.patch("pkg.fn") is not a route


def test_touched_routes() -> None:
    post = resolve_routes(DEMO_ROUTES)[1]
    assert touched_routes(DEMO_ROUTES, {post.start_line}) == [post]  # the decorator line counts
    assert touched_routes(DEMO_ROUTES, {1}) == []
    assert touched_routes(DEMO_ROUTES, set()) == []
    [broken] = touched_routes("def (:\n", {1})
    assert broken.resolved is False


PAY = ["@payments-team"]


@pytest.mark.parametrize(
    ("method", "path", "level", "decided_by", "owners"),
    [
        ("POST", "/v1/payments/{id}/discount", Level.FORBIDDEN, 'routes[0] "POST /v1/payments/*" -> critical', PAY),  # noqa: E501
        ("POST", "/v1/payments/123/discount", Level.FORBIDDEN, 'routes[0] "POST /v1/payments/*" -> critical', PAY),  # noqa: E501
        ("GET", "/v1/admin/orders/{id}", Level.COMMENT, 'routes[1] "* /v1/admin/*" -> high', []),
        ("GET", "/v1/public/orders/{id}", Level.SUGGEST, 'routes[2] "GET /v1/public/*" -> medium', []),  # noqa: E501
        ("GET", "/v1/payments/{id}", Level.SUGGEST, "routes: GET /v1/payments/{id} unlisted -> default_sensitivity medium", []),  # noqa: E501
    ],
)  # fmt: skip
def test_route_level(
    cfg: AutonomyConfig, method: str, path: str, level: Level, decided_by: str, owners: list[str]
) -> None:
    assert route_level(Route(method, path, 1, 2, True), cfg) == (level, decided_by, owners)


def test_unresolved_route_uses_default(cfg: AutonomyConfig) -> None:
    level, by, owners = route_level(Route("POST", "/v1/payments/x", 1, 2, False), cfg)
    assert level is Level.SUGGEST and owners == []
    assert by == "routes: unresolved -> default_sensitivity medium"
