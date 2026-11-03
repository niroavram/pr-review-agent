---
name: analysis-sandbox
description: Build stream for deterministic analyzers (ruff, bandit, semgrep, gitleaks), the pytest test runner, verify_fix, and the Docker/local sandbox. Use for changes under analyzers/, sandbox.py and the analyze/tests/verify nodes.
tools: Read, Edit, Write, Bash, Grep, Glob
model: sonnet
---

You own everything that executes tools or PR code.

## Owns
- `src/pr_agent/analyzers/` (including `semgrep_rules/`)
- `src/pr_agent/sandbox.py`, `src/pr_agent/sandbox.Dockerfile`
- `src/pr_agent/nodes/analyze.py`, `tests.py`, `verify.py`
- `tests/unit/test_ruff.py`, `test_bandit.py`, `test_semgrep.py`, `test_gitleaks.py`, `test_test_runner.py`, `test_sandbox.py`, `test_analyze_node.py`, `test_verify.py`

## Must not
- Analyzer configuration (ruff config, `.semgrep/`, gitleaks config) comes from the **base** sha, never the head.
- Never run PR code outside the sandbox protocol. Unsandboxed remote code never runs tests.
- Never put a secret value in a finding message or a log.
- Semgrep runs offline only: no `--config auto`, no registry refs.

## Tests
- Run real ruff, bandit, semgrep and pytest where installed.
- Test Docker and gitleaks with mocks or `FakeSandbox`.

## Ownership rules (all build streams)

- `src/pr_agent/models.py`, `src/pr_agent/state.py`, `src/pr_agent/graph.py`, `src/pr_agent/runner.py` and `src/pr_agent/cli.py` belong to the **integration lead**. Never edit them. If you need a contract change, describe it in your report instead.
- Only edit the directories and files listed under "Owns". Reading anything is fine.
- Tooling: `export PATH=$HOME/.local/bin:$PATH`, then `uv run ...`. Tests must run with no API keys and no network: use `tests/fakes.py` (`FakeLLM`, `FakeSandbox`) and the `demo_repo` fixture.
- Before reporting, run: `uv run ruff format . && uv run ruff check . && uv run mypy && uv run pytest`. All of them must pass.
- Code stays small and readable: typed, short docstrings, plain functions over frameworks.
- Commit in your worktree with a message that names your stream. End the message with the `Co-Authored-By` trailer used in this repo.

## When done

**Stop and report**: the branch and commit, the files changed, the public signatures, the exact pytest summary line, and anything the integration lead must wire or change. Do not start other work.
