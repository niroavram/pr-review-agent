# pr-agent: agentic PR review & autofix

A LangGraph workflow that reviews a pull request, runs static analysis and tests, finds bugs,
security problems and convention violations, proposes fixes, has them critiqued and verified,
and applies them only within deterministic autonomy boundaries read from the base branch.
Traced and evaluated with LangSmith.

## Documentation

- [Implementation plan (MVP)](docs/IMPLEMENTATION_PLAN.md): scope, decisions, autonomy boundaries, waves, eval cases
- [Design (production architecture)](docs/DESIGN.md): threat model, scalability, production path

## Quick start

```bash
cp .env.example .env        # add ANTHROPIC_API_KEY and LANGSMITH_API_KEY
uv run pr-agent demo        # builds the demo repo and reviews seeded PR 01
```
