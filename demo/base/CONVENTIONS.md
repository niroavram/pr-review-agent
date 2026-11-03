# Demo Shop conventions

Every rule has a stable ID. Reviews must cite the ID they apply.

## CONV-001: Money is integer cents
Store and compute money as `int` cents. Never use `float` for amounts.

## CONV-002: No `print` in library code
Use `logging.getLogger(__name__)` in `src/`. `print` is fine only in `scripts/`.

## CONV-003: Database access goes through `src/store`
Route handlers and services never call `conn.execute` directly; they call a function in `src/store`.

## CONV-004: Parameterized SQL only
SQL is always built with `?` placeholders and a parameter tuple. Never interpolate values into SQL strings.

## CONV-005: Public functions are typed
Every public function (no leading underscore) in `src/` has type hints for all parameters and the return value.
