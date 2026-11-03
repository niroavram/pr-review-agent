# pr-agent: agentic PR review & autofix

The agent improves pull requests: it reviews, fixes, and re-verifies in loops until every finding is resolved. When it can't resolve something safely, it stops and escalates: it asks the author a question or requests a human review.

It is built with **LangGraph**: fan-out reviewers, a propose → critique → verify subgraph with a revise loop, a deterministic policy gate with `interrupt()` for human approval, and SQLite checkpoints for resume. It is traced and evaluated with **LangSmith**. Deterministic analyzers (ruff, bandit, semgrep, gitleaks, pytest) provide the evidence. LLM agents (Claude) find logic bugs and convention violations and propose fixes. **Autonomy boundaries** read from the PR's *base* branch decide, in code, what may be changed automatically.

## Documentation

The docs folder has the full plan. IMPLEMENTATION_PLAN.md covers how the system is built, DESIGN.md covers the production architecture and the trade-offs behind it, and AGENTS.md describes each agent's role, what it gets, what it returns, and its limits.

- [Implementation plan (MVP)](docs/IMPLEMENTATION_PLAN.md): scope, decisions, autonomy boundaries, graph, rule learning, convergence loop, waves, eval cases
- [Design (production architecture)](docs/DESIGN.md): threat model, performance, scalability, production path
- [Agents and roles](docs/AGENTS.md): every LLM agent and deterministic role, with inputs, output schema, permissions, escalation and eval metric

## Quick start

```bash
cp .env.example .env        # add ANTHROPIC_API_KEY and LANGSMITH_API_KEY
uv run pr-agent demo        # builds the demo repo and reviews seeded PR 01 (SQL injection)
```

Other commands:

```bash
uv run pr-agent review --local <repo> --base main --head <branch>
uv run pr-agent review https://github.com/<owner>/<repo>/pull/<n>   # GITHUB_TOKEN optional (read-only)
uv run pr-agent resume <run-id> --approve F1,F3                     # approve `suggest` fixes later
uv run pr-agent init <repo> && uv run pr-agent check-config <repo>  # autonomy boundaries
uv run pr-agent eval --offline                                      # 12 seeded cases, scripted LLM, no keys
uv run pr-agent eval                                                # same cases through LangSmith evaluate()
```

Outputs go to `.pr-agent/runs/<run-id>/`: `review.md`, `review.json` and `patches/`. Fixes that may ship are committed to a local `autofix/<pr>` branch; nothing is ever pushed.

## Status

Last updated: after v1-submission (e2e hang fixed).

### Implemented and tested

Everything below ran in this environment: `ruff check`, `mypy` and `pytest` give **349 passed**. The tests run with no API keys and no network, using a fake/scripted LLM and the real tools.

- **Ingest:** local branches (`--local`) and GitHub PR URLs, using REST metadata, a partial clone and `refs/pull/N/head`. URL mode is tested against a mocked API and a local bare repo, not against github.com.
- **Diff parsing and triage:** file filters, docs/config-only PRs.
- **Analyzers:** ruff (with deterministic fixes), bandit, and semgrep with vendored offline rules plus the base branch's `.semgrep/`. All analyzer configs are read from the **base** branch.
- **Test runner:** pytest, reporting only failures the PR introduced (it compares against base).
- **LLM agents:** bug, security and conventions reviewers, fix_proposer (search/replace edits turned into a diff deterministically) and fix_critic, with up to 2 revisions. PR content is wrapped as untrusted, prompt-injection hardening is in place, and CONV-IDs are validated.
- **verify_fix:** the patch applies, the finding is gone, no new blocking findings appear, and tests pass.
- **Autonomy boundaries**, enforced deterministically from the base-branch `.pr-agent.yml`:
  - paths, routes (resolved from FastAPI/Flask code with `ast`), fix types, public API changes (AST signature diff), lint rules, limits and hard rules;
  - fail-closed on a missing or invalid config;
  - every decision is named by its `decided_by` rule;
  - `pr-agent init` / `check-config`.
- **Approval gate:** `interrupt()` with interactive approval, plus `pr-agent resume`, which time-travels to the gate without re-running the LLMs.
- **Publishing:** review.md, review.json, patch files, and a local `autofix/<pr>` branch written via a temporary worktree.
- **Redaction:** secrets are redacted in the review output and in the LangSmith payload hooks.
- **Demo and evals:**
  - a demo repo with **12 seeded cases**, where the secret is derived at build time and never committed;
  - an offline eval with a scripted LLM;
  - evaluators: precision, recall, policy_correct, owners_tagged, fix_verified, applied, clean_zero, injection_unchanged, config_tamper_ignored;
  - offline end-to-end tests for cases 01, 09, 10, 11 and 12.

### Implemented, not verified here

- **Live LLM and LangSmith runs** (`pr-agent demo`, `pr-agent eval` without `--offline`): no API keys were available in the build environment, so no real model output or LangSmith trace has been observed yet. `evals/results.md` is from the **offline** (scripted LLM) run.
- **Docker sandbox** (`--network none`, CPU/memory/pid limits, read-only root, dropped capabilities) and **gitleaks**: only command construction and output parsing are unit-tested, because no Docker daemon or gitleaks binary was available. Without Docker the tool falls back to a local temp dir and shows a banner.
- **`--post`** (posting the review to GitHub): tested against a mocked API only.

### Designed, not built yet

- **Convergence loop and escalation**: re-run on `autofix/<pr>` until no findings / no progress / `max_rounds`, then "Needs your input" escalations. The code exists behind `PR_AGENT_CONVERGE=1` and is **disabled by default** because it hasn't been verified yet. Design: [plan §5, convergence loop](docs/IMPLEMENTATION_PLAN.md#convergence-loop-and-escalation), [AGENTS.md escalation matrix](docs/AGENTS.md#escalation-matrix-convergence-loop). Eval case 13 isn't added yet.
- **Rule learning**: rule_drafter, verify_rule, "Prevent this next time". Design: [plan §5, rule learning](docs/IMPLEMENTATION_PLAN.md#rule-learning), [DESIGN.md §7](docs/DESIGN.md#7-rule-learning-prevent-this-next-time), [AGENTS.md rule_drafter](docs/AGENTS.md#rule_drafter-designed-not-built-yet).
- **Generated role cards**: `docs/AGENTS.md` generated from prompt headers and checked by a unit test. Today it is hand-written.
- **The production path** (GitHub App, webhooks, queue, Postgres, k8s sandbox, feedback loop): [DESIGN.md §9](docs/DESIGN.md#9-production-path-what-the-mvp-leaves-out-and-how-each-piece-comes-back).

### Known issues

- ~~`tests/test_graph_e2e.py` hangs~~ **Fixed.** The escalation step resumed the graph with an empty dict, which LangGraph reads as an interrupt-id map, so the same interrupt fired forever. It now resumes with a list of pairs. The e2e tests are re-enabled and pass with the convergence loop both off and on.
- Offline eval ([evals/results.md](evals/results.md), scripted LLM): precision 100%, recall 94%, fix pass rate 100% (12/12), policy_correct 91%. There are two gaps:
  - Case 05, recall 0.67: the UP045 fix leaves an unused import, which the next round of the convergence loop would fix.
  - Case 06, policy_correct 0: the CONV-001 fix changes a public signature, so the policy correctly downgrades it to `comment`, but the case's expectation still says `suggest`. The expectation needs revisiting.
- `src/` is about 4.5k lines including docstrings and blank lines, above the 2–2.5k target.

## Development

```bash
uv run ruff check . && uv run mypy && uv run pytest
```

`main` always passes ruff and pytest. Work happens on `dev`, and every merge to `main` updates this Status section.
