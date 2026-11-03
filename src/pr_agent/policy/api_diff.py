"""Public API signature diff (AST only). A changed or removed public signature caps autonomy.

Public = no leading underscore (dunders such as `__init__` count as public). We compare
top-level functions, classes, and methods of public classes. Additions are not changes.
"""

from __future__ import annotations

import ast

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


def _is_public(name: str) -> bool:
    return not name.startswith("_") or (name.startswith("__") and name.endswith("__"))


def signature(fn: FunctionNode) -> str:
    """Readable signature covering what callers depend on.

    Parameter names and kinds, which ones have defaults (not their values), *args/**kwargs
    and the return annotation, e.g. `f(a, b=..., *args, c, **kw) -> int`.
    """
    a = fn.args
    positional = a.posonlyargs + a.args
    first_default = len(positional) - len(a.defaults)
    parts = [p.arg + ("=..." if i >= first_default else "") for i, p in enumerate(positional)]
    if a.posonlyargs:
        parts.insert(len(a.posonlyargs), "/")
    if a.vararg:
        parts.append(f"*{a.vararg.arg}")
    elif a.kwonlyargs:
        parts.append("*")
    # kw_defaults is aligned with kwonlyargs and holds None for "no default"
    kw_pairs = zip(a.kwonlyargs, a.kw_defaults, strict=True)
    parts += [k.arg + ("" if d is None else "=...") for k, d in kw_pairs]
    if a.kwarg:
        parts.append(f"**{a.kwarg.arg}")
    returns = f" -> {ast.unparse(fn.returns)}" if fn.returns else ""
    return f"{fn.name}({', '.join(parts)}){returns}"


def public_api(source: str) -> dict[str, str]:
    """Qualified public name -> signature ("class" for a class). Raises SyntaxError."""
    api: dict[str, str] = {}
    for node in ast.parse(source).body:
        if isinstance(node, FunctionNode) and _is_public(node.name):
            api[node.name] = signature(node)
        elif isinstance(node, ast.ClassDef) and _is_public(node.name):
            api[node.name] = "class"
            for item in node.body:
                if isinstance(item, FunctionNode) and _is_public(item.name):
                    api[f"{node.name}.{item.name}"] = signature(item)
    return api


def public_api_changes(before: str, after: str) -> list[str]:
    """Human-readable changed/removed public signatures; unparseable code counts as a change."""
    try:
        old, new = public_api(before), public_api(after)
    except SyntaxError as e:
        return [f"cannot parse source (line {e.lineno}): treated as an API change"]
    changes: list[str] = []
    for name, sig in old.items():
        if name not in new:
            changes.append(f"removed {name}")
        elif new[name] != sig:
            changes.append(f"changed {name}: {sig} -> {new[name]}")
    return changes
