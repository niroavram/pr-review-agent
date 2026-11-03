"""`pr-agent` command line."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any

import typer
from dotenv import load_dotenv

from pr_agent.demo import build as build_demo
from pr_agent.demo import list_cases, load_case
from pr_agent.deps import Deps
from pr_agent.ingest.local import load_local
from pr_agent.models import PRContext
from pr_agent.policy.config import CONFIG_FILE, TEMPLATE, parse_config
from pr_agent.runner import RunResult, resume_review, run_review
from pr_agent.settings import Settings

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Agentic PR review & autofix")


@app.callback()
def _main() -> None:
    load_dotenv()


@app.command()
def init(path: Path = typer.Argument(Path(".")), force: bool = False) -> None:
    """Copy the autonomy-boundaries template into a repo."""
    dest = path / CONFIG_FILE
    if dest.exists() and not force:
        typer.echo(f"{dest} exists (use --force to overwrite)")
        raise typer.Exit(1)
    shutil.copyfile(TEMPLATE, dest)
    typer.echo(f"wrote {dest}")


@app.command("check-config")
def check_config(path: Path = typer.Argument(Path("."))) -> None:
    """Validate a repo's .pr-agent.yml (or a file path)."""
    file = path if path.is_file() else path / CONFIG_FILE
    if not file.exists():
        typer.echo(f"✗ {file} not found -> agent runs fail-closed (suggest-only)")
        raise typer.Exit(1)
    try:
        parse_config(file.read_text())
    except ValueError as e:
        typer.echo(f"✗ {file}: {e}")
        raise typer.Exit(1) from e
    typer.echo(f"✓ {file} is valid")


def _deps(interactive: bool) -> tuple[Deps, list[str]]:
    from pr_agent.agents.llm import AnthropicLLM
    from pr_agent.sandbox import get_sandbox

    if not os.environ.get("ANTHROPIC_API_KEY"):
        typer.echo("ANTHROPIC_API_KEY is not set (copy .env.example to .env).")
        raise typer.Exit(2)
    settings = Settings()
    sandbox, banners = get_sandbox(settings)
    return Deps(
        llm=AnthropicLLM(settings), sandbox=sandbox, settings=settings, interactive=interactive
    ), banners


def _ask(pending: list[dict[str, Any]]) -> list[str]:
    """Interactive approval of `suggest` fixes (the local stand-in for /autofix apply)."""
    typer.echo("\nFixes that need approval (level: suggest):")
    for p in pending:
        typer.echo(f"  {p['id']}  {p['file']}: {p['message']}")
    answer = typer.prompt("Approve which? (comma-separated ids, 'all', or empty)", default="")
    if answer.strip().lower() == "all":
        return [p["id"] for p in pending]
    return [a.strip() for a in answer.split(",") if a.strip()]


def _report(result: RunResult) -> None:
    out = Path(result.state.get("output_dir", ""))
    findings = result.state.get("final_findings", [])
    typer.echo(f"\nRun {result.run_id}: {len(findings)} finding(s)")
    typer.echo(f"Review:  {out / 'review.md'}")
    if result.trace_url:
        typer.echo(f"Trace:   {result.trace_url}")


def _run(ctx: PRContext, interactive: bool) -> RunResult:
    deps, banners = _deps(interactive)
    approver = _ask if interactive and sys.stdin.isatty() else (lambda pending: [])
    result = run_review(ctx, deps, approver=approver, banners=banners)
    _report(result)
    return result


@app.command()
def review(
    target: str = typer.Argument(None, help="GitHub PR URL"),
    local: Path = typer.Option(None, "--local", help="Local repo path (reviews --head vs --base)"),
    base: str = typer.Option("main", "--base"),
    head: str = typer.Option("HEAD", "--head"),
    no_input: bool = typer.Option(False, "--no-input", help="Never prompt; approve nothing"),
) -> None:
    """Review a PR (GitHub URL) or a local branch."""
    if local:
        ctx = load_local(local, base, head)
    elif target:
        from pr_agent.ingest.github import load_github

        ctx = load_github(target, Settings().work_dir)
    else:
        typer.echo("Give a GitHub PR URL or --local <repo-path>.")
        raise typer.Exit(2)
    _run(ctx, interactive=not no_input)


@app.command()
def resume(
    run_id: str,
    approve: str = typer.Option("", "--approve", help="Comma-separated finding ids, e.g. F1,F3"),
) -> None:
    """Approve `suggest` fixes of an earlier run (the /autofix apply equivalent)."""
    deps, _ = _deps(interactive=False)
    ids = [a.strip() for a in approve.split(",") if a.strip()]
    _report(resume_review(run_id, deps, ids))


@app.command()
def demo(case: str = typer.Option("01", help="Seeded case number to review")) -> None:
    """Build the demo repo and review one seeded case (default: 01, SQL injection)."""
    repo = build_demo(Settings().work_dir / "demo-repo")
    meta = next(load_case(c) for c in list_cases() if c.name.startswith(case))
    typer.echo(f"Demo repo: {repo}\nReviewing {meta['branch']}: {meta['title']}")
    _run(load_local(repo, "main", meta["branch"]), interactive=False)


@app.command("eval")
def eval_cmd(
    offline: bool = typer.Option(False, help="Scripted LLM, no API keys, no LangSmith upload"),
    case: list[str] = typer.Option(None, help="Only these case prefixes, e.g. --case 01"),
) -> None:
    """Run the seeded eval cases (LangSmith evaluate() unless --offline)."""
    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root))  # evals/ lives next to src/, not inside the package
    from evals.run import main as run_evals

    if not offline and not os.environ.get("LANGSMITH_API_KEY"):
        typer.echo("LANGSMITH_API_KEY is not set; use --offline or add it to .env.")
        raise typer.Exit(2)
    typer.echo(f"Results: {run_evals(offline=offline, cases=case or None)}")


if __name__ == "__main__":
    app()
