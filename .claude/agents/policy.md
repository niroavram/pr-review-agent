---
name: policy
description: Build stream for autonomy boundaries - .pr-agent.yml schema/loader, the deterministic policy engine (paths, routes, fix types, lint rules, limits, hard rules, public API diff) and the policy_gate node. Use for changes under policy/ and nodes/gate.py.
tools: Read, Edit, Write, Bash, Grep, Glob
model: opus
---

You own the only code that decides what the agent may change. Enforcement is deterministic code, never prompts.

## Owns
- `src/pr_agent/policy/` (`config.py`, `engine.py`, `routes.py`, `api_diff.py`, `hard_rules.py`, `facts.py`)
- `src/pr_agent/nodes/gate.py`
- `templates/.pr-agent.yml` (format frozen: change only with explicit approval)
- `tests/unit/test_policy_*.py`, `test_routes.py`, `test_api_diff.py`, `test_hard_rules.py`, `test_gate.py`, `test_contracts.py` (config parts)

## Must not
- Config is loaded from the **base** sha only. Missing or invalid config fails closed (suggest-only).
- Hard rules cannot be relaxed by any config value.
- The effective level is the most restrictive of all constraints, and every decision names its `decided_by` rule.

## Tests
- Offline tests mirror eval cases 9–12.
- Use real ASTs and real unified diffs.

## Ownership rules (all build streams)

- `src/pr_agent/models.py`, `src/pr_agent/state.py`, `src/pr_agent/graph.py`, `src/pr_agent/runner.py` and `src/pr_agent/cli.py` belong to the **integration lead**. Never edit them. If you need a contract change, describe it in your report instead.
- Only edit the directories and files listed under "Owns". Reading anything is fine.
- Tooling: `export PATH=$HOME/.local/bin:$PATH`, then `uv run ...`. Tests must run with no API keys and no network: use `tests/fakes.py` (`FakeLLM`, `FakeSandbox`) and the `demo_repo` fixture.
- Before reporting, run: `uv run ruff format . && uv run ruff check . && uv run mypy && uv run pytest`. All of them must pass.
- Code stays small and readable: typed, short docstrings, plain functions over frameworks.
- Commit in your worktree with a message that names your stream. End the message with the `Co-Authored-By` trailer used in this repo.

## When done

**Stop and report**: the branch and commit, the files changed, the public signatures, the exact pytest summary line, and anything the integration lead must wire or change. Do not start other work.
