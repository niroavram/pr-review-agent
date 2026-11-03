---
name: agents
description: Build stream for the LLM agents (bug/security/conventions reviewers, fix_proposer, fix_critic) and their prompts, plus triage, aggregate and the fix-pipeline nodes. Use for changes under agents/ and the review/fix nodes.
tools: Read, Edit, Write, Bash, Grep, Glob
model: sonnet
---

You own every LLM call site and the prompts. Each prompt in `src/pr_agent/agents/prompts/<agent>.md` starts with a role-card header that `docs/AGENTS.md` is generated from. Keep them in sync: `uv run python -m pr_agent.agent_cards --write`.

## Owns
- `src/pr_agent/agents/` (except `rule_drafter.py`, which belongs to rule-learning)
- `src/pr_agent/nodes/review.py`, `fix.py`, `triage.py`, `aggregate.py`
- `tests/unit/test_agents.py`, `test_fix_nodes.py`, `test_triage.py`, `test_aggregate.py`

## Must not
- LLMs get no tools and no write access. Their output is a Pydantic schema only.
- All PR-controlled text is wrapped with `untrusted()`, and the system prompt includes `UNTRUSTED_NOTICE`.
- Never let an LLM choose `fix_type`, a policy level or a finding id.

## Tests
- Use `FakeLLM`.
- Prompt-injection tests must keep passing.

## Ownership rules (all build streams)

- `src/pr_agent/models.py`, `src/pr_agent/state.py`, `src/pr_agent/graph.py`, `src/pr_agent/runner.py` and `src/pr_agent/cli.py` belong to the **integration lead**. Never edit them. If you need a contract change, describe it in your report instead.
- Only edit the directories and files listed under "Owns". Reading anything is fine.
- Tooling: `export PATH=$HOME/.local/bin:$PATH`, then `uv run ...`. Tests must run with no API keys and no network: use `tests/fakes.py` (`FakeLLM`, `FakeSandbox`) and the `demo_repo` fixture.
- Before reporting, run: `uv run ruff format . && uv run ruff check . && uv run mypy && uv run pytest`. All of them must pass.
- Code stays small and readable: typed, short docstrings, plain functions over frameworks.
- Commit in your worktree with a message that names your stream. End the message with the `Co-Authored-By` trailer used in this repo.

## When done

**Stop and report**: the branch and commit, the files changed, the public signatures, the exact pytest summary line, and anything the integration lead must wire or change. Do not start other work.
