"""HTTP routes from Python source (AST only, never imported) and their sensitivity.

FastAPI style: `router = APIRouter(prefix="/v1")` + `@router.post("/payments/{id}")`.
Flask style:   `app = Flask(__name__)` + `@app.route("/x", methods=["POST"])` (default GET).
Anything we cannot read as a string literal is an *unresolved* route -> default sensitivity.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from fnmatch import fnmatchcase

from pr_agent.models import Level
from pr_agent.policy.config import AutonomyConfig

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
# constructor name -> keyword holding the path prefix
ROUTER_FACTORIES = {
    "APIRouter": "prefix",
    "FastAPI": "prefix",
    "Flask": "",
    "Blueprint": "url_prefix",
}


@dataclass(frozen=True)
class Route:
    method: str  # "POST", or "*" when unknown
    path: str  # full path including the router prefix, e.g. "/v1/payments/{order_id}/discount"
    start_line: int  # first decorator line
    end_line: int  # last line of the handler body
    resolved: bool  # False when the path, prefix or methods are not string literals


def _literal(node: ast.expr | None) -> str | None:
    """The value of a string literal, else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _call_name(call: ast.Call) -> str | None:
    """`APIRouter(...)` or `fastapi.APIRouter(...)` -> "APIRouter"."""
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _keyword(call: ast.Call, name: str) -> ast.keyword | None:
    return next((k for k in call.keywords if k.arg == name), None)


def _routers(tree: ast.Module) -> dict[str, str | None]:
    """Module-level router/app variables -> their prefix ("" if none, None if not a literal)."""
    routers: dict[str, str | None] = {}
    for stmt in tree.body:
        if not (isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call)):
            continue
        factory = _call_name(stmt.value)
        if factory not in ROUTER_FACTORIES:
            continue
        kw = _keyword(stmt.value, ROUTER_FACTORIES[factory]) if ROUTER_FACTORIES[factory] else None
        prefix = "" if kw is None else _literal(kw.value)
        for target in stmt.targets:
            if isinstance(target, ast.Name):
                routers[target.id] = prefix
    return routers


def _methods(call: ast.Call, verb: str) -> list[str] | None:
    """HTTP methods of one decorator call; None when `methods=` is not a literal list."""
    if verb != "route":
        return [verb.upper()]
    kw = _keyword(call, "methods")
    if kw is None:
        return ["GET"]  # Flask default
    if not isinstance(kw.value, ast.List | ast.Tuple | ast.Set):
        return None
    names = [_literal(e) for e in kw.value.elts]
    if any(n is None for n in names):
        return None
    return [n.upper() for n in names if n is not None]


def _decorator_routes(
    deco: ast.expr, routers: dict[str, str | None], start: int, end: int
) -> list[Route]:
    """Routes declared by one decorator such as `@router.post("/x")`; [] if not a route."""
    if not (isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute)):
        return []
    verb, owner = deco.func.attr, deco.func.value
    if verb not in HTTP_METHODS | {"route"} or not isinstance(owner, ast.Name):
        return []
    raw = deco.args[0] if deco.args else getattr(_keyword(deco, "path"), "value", None)
    path = _literal(raw)
    if owner.id not in routers and not (path or "").startswith("/"):
        return []  # e.g. `@mock.patch("pkg.fn")`: an unknown object, and not URL-shaped
    # a URL-shaped decorator on an unknown receiver (router imported from elsewhere): prefix unknown
    prefix = routers.get(owner.id)
    methods = _methods(deco, verb)
    resolved = prefix is not None and path is not None and methods is not None
    full = f"{prefix or ''}{path or ''}"
    return [Route(m, full, start, end, resolved) for m in (methods or ["*"])]


def resolve_routes(source: str) -> list[Route]:
    """All route handlers in a module. Raises SyntaxError on unparseable source."""
    tree = ast.parse(source)
    routers = _routers(tree)
    routes: list[Route] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) or not node.decorator_list:
            continue
        start = min(d.lineno for d in node.decorator_list)
        end = node.end_lineno or node.lineno
        for deco in node.decorator_list:
            routes += _decorator_routes(deco, routers, start, end)
    return routes


def touched_routes(source_after: str, changed_lines: set[int]) -> list[Route]:
    """Routes whose span (decorators + body) contains a changed line.

    Unparseable source with changes fails closed: one unresolved route covering everything.
    """
    if not changed_lines:
        return []
    try:
        routes = resolve_routes(source_after)
    except SyntaxError:
        return [Route("*", "", 1, max(changed_lines), resolved=False)]
    return [r for r in routes if any(r.start_line <= n <= r.end_line for n in changed_lines)]


def _matches(rule: str, route: Route) -> bool:
    """`"POST /v1/payments/*"` vs a route; method `*` = any, `*` in the path matches the rest."""
    method, _, pattern = rule.partition(" ")
    return (method == "*" or method.upper() == route.method) and fnmatchcase(route.path, pattern)


def route_level(route: Route, cfg: AutonomyConfig) -> tuple[Level, str, list[str]]:
    """Level for one route. Several matching rules: most restrictive wins, owners are unioned."""
    default = Level.parse(cfg.levels[cfg.default_sensitivity])
    if not route.resolved:
        return default, f"routes: unresolved -> default_sensitivity {cfg.default_sensitivity}", []
    best: tuple[Level, str] | None = None
    owners: list[str] = []
    for i, rule in enumerate(cfg.routes):
        if not _matches(rule.match, route):
            continue
        level = Level.parse(cfg.levels[rule.sensitivity])
        if best is None or level > best[0]:
            best = (level, f'routes[{i}] "{rule.match}" -> {rule.sensitivity}')
        owners += [o for o in rule.owners if o not in owners]
    if best is None:
        by = f"routes: {route.method} {route.path} unlisted -> default_sensitivity"
        return default, f"{by} {cfg.default_sensitivity}", []
    return best[0], best[1], owners
